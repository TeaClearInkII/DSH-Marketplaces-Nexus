/**
 * DSH 万市枢纽 —— Host 侧插件
 *
 * 职责：
 *  - nexus.load      读取市场数据（本地文件优先，远程 GitHub raw 回退）
 *  - nexus.installed 读取 profile 已安装依赖与 bundle 列表
 *  - nexus.install / nexus.uninstall  安装/卸载（dsh plugin → pnpm 回退 + bundle 注册）
 *  - nexus.setEnabled 停用/启用（纯文件操作 profile 的 dsh.profile.bundles，不依赖 shell）
 *  - nexus.latest    npm registry 最新版本查询
 *  - nexus.env       本机环境信息（工作区/Profile/Node/pnpm/npm/dsh/平台）
 */
module.exports = {
  name: 'dsh-marketplaces-nexus',
  config: {},
  apply(ctx) {
    const fs = ctx.get('fs')
    if (fs === undefined) return

    const PROFILE_CANDIDATES = [
      'C:/Users/cc/.dsh/profiles/web/package.json',
      'profiles/web/package.json',
      '../profiles/web/package.json',
    ]

    // 仓库地址；也可通过插件 config 的 dataUrl 覆盖
    const REMOTE_DATA_URL =
      'https://raw.githubusercontent.com/TeaClearInkII/DSH-Marketplaces-Nexus/main/docs/marketplaces.json'
    const cfg = this.config || {}
    const remoteDataUrl = cfg.dataUrl || REMOTE_DATA_URL

    async function locateData() {
      const policy = ctx.get('sandboxPolicy')
      const candidates = []
      if (policy && typeof policy.workspaceRoot === 'string' && policy.workspaceRoot) {
        candidates.push(policy.workspaceRoot.replace(/\\/g, '/') + '/docs/marketplaces.json')
      }
      candidates.push('D:/个人工程文件/DeepSeekHarness/DSH 万市枢纽/docs/marketplaces.json')
      candidates.push('docs/marketplaces.json')
      // 包内数据快照（node_modules/dsh-marketplaces-nexus/docs/marketplaces.json）
      if (typeof __dirname === 'string') {
        candidates.push(__dirname.replace(/\\/g, '/') + '/../docs/marketplaces.json')
      }
      for (const path of candidates) {
        try {
          const target = await fs.resolve(path)
          const info = await fs.stat(target)
          if (info !== undefined) return { path, target }
        } catch (err) {
          // try the next candidate
        }
      }
      return null
    }

    async function fetchRemoteData() {
      const web = ctx.get('web')
      if (web === undefined) return null
      try {
        const res = await web.fetch({ url: remoteDataUrl })
        const raw = typeof res.body === 'string' ? res.body : res.content !== undefined ? res.content : null
        if (raw === null) return null
        const data = JSON.parse(raw)
        return { path: remoteDataUrl, data }
      } catch (err) {
        return null
      }
    }

    async function locateProfile() {
      for (const path of PROFILE_CANDIDATES) {
        try {
          const target = await fs.resolve(path)
          const info = await fs.stat(target)
          if (info !== undefined) return { path, target }
        } catch (err) {
          // try the next candidate
        }
      }
      return null
    }

    async function runCommand(command, args, cwd) {
      const shell = ctx.get('shell')
      if (shell === undefined) return { ok: false, error: 'shell 服务不可用' }
      try {
        const spec = shell.resolve({ command: command, args: args, cwd: cwd, timeout: 300000 })
        const res = await shell.run(spec)
        const code = res && res.exitCode
        return {
          ok: code === 0,
          code: code,
          out: (res && res.stdout) || '',
          err: (res && res.stderr) || '',
        }
      } catch (e) {
        return { ok: false, error: String((e && e.message) || e) }
      }
    }

    async function reconcileBundles(profileTarget, profileDir) {
      try {
        const text = await fs.readText(profileTarget)
        const pkg = JSON.parse(text)
        const deps = Object.keys(pkg.dependencies || {})
        const bundles = (pkg.dsh && pkg.dsh.profile && pkg.dsh.profile.bundles) || []
        let changed = false
        for (const name of deps) {
          try {
            const depPath = profileDir + '/node_modules/' + name + '/package.json'
            const t = await fs.resolve(depPath)
            const info = await fs.stat(t)
            if (info === undefined) continue
            const depText = await fs.readText(t)
            const dep = JSON.parse(depText)
            if (dep.dsh && dep.dsh.bundle && dep.dsh.bundle.patch && bundles.indexOf(name) === -1) {
              bundles.push(name)
              changed = true
            }
          } catch (e) {
            // skip unreadable dep
          }
        }
        if (changed) {
          pkg.dsh = pkg.dsh || {}
          pkg.dsh.profile = pkg.dsh.profile || {}
          pkg.dsh.profile.bundles = bundles
          await fs.writeText(profileTarget, JSON.stringify(pkg, null, 2))
        }
        return changed
      } catch (e) {
        return false
      }
    }

    function matchPackageName(pkg, spec) {
      const deps = pkg.dependencies || {}
      for (const name of Object.keys(deps)) {
        const v = String(deps[name] || '')
        if (spec === name || v.indexOf(spec) !== -1 || spec.indexOf(name) !== -1 || spec.indexOf(v) !== -1) return name
      }
      const bundles = (pkg.dsh && pkg.dsh.profile && pkg.dsh.profile.bundles) || []
      for (const b of bundles) {
        if (spec.indexOf(b) !== -1 || b.indexOf(spec) !== -1) return b
      }
      return null
    }

    harness.handle('nexus.load', async () => {
      try {
        const found = await locateData()
        if (found !== null) {
          const text = await fs.readText(found.target)
          const data = JSON.parse(text)
          return { ok: true, source: found.path, data }
        }
        const remote = await fetchRemoteData()
        if (remote !== null) return { ok: true, source: remote.path, data: remote.data }
        return { ok: false, error: '未找到本地数据文件，且远程数据源不可用' }
      } catch (err) {
        return { ok: false, error: String((err && err.message) || err) }
      }
    })

    harness.handle('nexus.installed', async () => {
      try {
        const profile = await locateProfile()
        if (profile === null) {
          return { ok: false, error: '未找到 profile package.json' }
        }
        const text = await fs.readText(profile.target)
        const pkg = JSON.parse(text)
        const deps = Object.keys(pkg.dependencies || {}).map(function (name) {
          return { name: name, value: pkg.dependencies[name] }
        })
        const bundles = (pkg.dsh && pkg.dsh.profile && pkg.dsh.profile.bundles) || []
        return { ok: true, deps: deps, bundles: bundles, profile: profile.path }
      } catch (err) {
        return { ok: false, error: String((err && err.message) || err) }
      }
    })

    harness.handle('nexus.install', async (args) => {
      if (!args || !args.spec) return { ok: false, error: '缺少安装标识' }
      const res = await runCommand('dsh', ['plugin', '--profile', 'web', 'add', args.spec], undefined)
      if (res.ok) return { ok: true, note: 'dsh plugin 安装成功' }
      const profile = await locateProfile()
      if (profile === null) return { ok: false, error: 'dsh plugin 失败：' + (res.err || res.error) + '；且无法定位 profile 目录用于 pnpm 回退' }
      const profileDir = String(profile.path).replace(/\/package\.json$/, '')
      const pnpmRes = await runCommand('pnpm', ['add', args.spec], profileDir)
      if (!pnpmRes.ok) {
        return { ok: false, error: 'dsh plugin 失败：' + (res.err || res.error) + '；pnpm 回退失败：' + (pnpmRes.err || pnpmRes.error || '') }
      }
      const changed = await reconcileBundles(profile.target, profileDir)
      return { ok: true, note: 'pnpm 安装成功' + (changed ? '，已注册为 bundle 层' : '（未检测到 dsh.bundle 声明，未注册为 bundle 层）') }
    })

    harness.handle('nexus.uninstall', async (args) => {
      if (!args || !args.spec) return { ok: false, error: '缺少卸载标识' }
      const res = await runCommand('dsh', ['plugin', '--profile', 'web', 'remove', args.spec], undefined)
      if (res.ok) return { ok: true, note: 'dsh plugin 卸载成功' }
      const profile = await locateProfile()
      if (profile === null) return { ok: false, error: 'dsh plugin 失败：' + (res.err || res.error) + '；且无法定位 profile 目录用于 pnpm 回退' }
      const profileDir = String(profile.path).replace(/\/package\.json$/, '')
      const pnpmRes = await runCommand('pnpm', ['remove', args.spec], profileDir)
      if (!pnpmRes.ok) {
        return { ok: false, error: 'dsh plugin 失败：' + (res.err || res.error) + '；pnpm 回退失败：' + (pnpmRes.err || pnpmRes.error || '') }
      }
      return { ok: true, note: 'pnpm 卸载成功' }
    })

    harness.handle('nexus.setEnabled', async (args) => {
      if (!args || !args.spec || typeof args.enabled !== 'boolean') return { ok: false, error: '参数错误' }
      const profile = await locateProfile()
      if (profile === null) return { ok: false, error: '未找到 profile package.json' }
      try {
        const text = await fs.readText(profile.target)
        const pkg = JSON.parse(text)
        const pkgName = matchPackageName(pkg, args.spec)
        if (pkgName === null) return { ok: false, error: '未在 profile 中找到匹配的包（' + args.spec + '）' }
        pkg.dsh = pkg.dsh || {}
        pkg.dsh.profile = pkg.dsh.profile || {}
        const bundles = (pkg.dsh.profile.bundles || []).slice()
        const idx = bundles.indexOf(pkgName)
        if (args.enabled && idx === -1) bundles.push(pkgName)
        if (!args.enabled && idx !== -1) bundles.splice(idx, 1)
        pkg.dsh.profile.bundles = bundles
        await fs.writeText(profile.target, JSON.stringify(pkg, null, 2))
        return { ok: true, note: (args.enabled ? '已启用' : '已停用') + ' ' + pkgName + '（bundles 列表已更新）' }
      } catch (e) {
        return { ok: false, error: String((e && e.message) || e) }
      }
    })

    harness.handle('nexus.latest', async (args) => {
      const web = ctx.get('web')
      if (web === undefined || !args || !args.pkg) return { ok: false, error: 'web 服务不可用或缺少包名' }
      try {
        const res = await web.fetch({ url: 'https://registry.npmjs.org/' + encodeURIComponent(args.pkg) + '/latest' })
        const raw = typeof res.body === 'string' ? res.body : res.content !== undefined ? res.content : null
        if (raw === null) return { ok: false, error: 'npm registry 响应格式异常' }
        const data = JSON.parse(raw)
        return { ok: true, version: data && data.version }
      } catch (err) {
        return { ok: false, error: String((err && err.message) || err) }
      }
    })

    harness.handle('nexus.env', async () => {
      const policy = ctx.get('sandboxPolicy')
      const info = {
        workspace: policy && typeof policy.workspaceRoot === 'string' ? policy.workspaceRoot : null,
        profile: null,
        node: null,
        pnpm: null,
        npm: null,
        dsh: null,
        platform: null,
      }
      try {
        const profile = await locateProfile()
        if (profile !== null) info.profile = profile.path
      } catch (e) {
        // ignore
      }
      const shell = ctx.get('shell')
      if (shell === undefined) {
        info.nodeError = 'shell 服务不可用'
      } else {
        const tasks = [
          ['node', ['-v'], 'node'],
          ['pnpm', ['-v'], 'pnpm'],
          ['npm', ['-v'], 'npm'],
          ['dsh', ['--version'], 'dsh'],
          ['node', ['-p', "process.platform + ' ' + process.arch"], 'platform'],
        ]
        for (const task of tasks) {
          try {
            const spec = shell.resolve({ command: task[0], args: task[1], timeout: 30000 })
            const res = await shell.run(spec)
            if (res && res.exitCode === 0) {
              info[task[2]] = String(res.stdout || '').trim()
            } else {
              info[task[2] + 'Error'] = 'exit ' + (res && res.exitCode) + ': ' + String((res && res.stderr) || '').slice(0, 120)
            }
          } catch (e) {
            info[task[2] + 'Error'] = String((e && e.message) || e).slice(0, 120)
          }
        }
      }
      return { ok: true, env: info }
    })
  },
}
