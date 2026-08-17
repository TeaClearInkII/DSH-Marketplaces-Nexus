/**
 * DSH 万市枢纽 —— Client 侧插件
 *
 * 在 DSH Web 设置页注册「万市枢纽」页面（settings.section）：
 * 本仓库信息卡 + 更多折叠（生态导航/学习开发/本机环境）+ 筛选/搜索/排序
 * + 市场卡片（分类/验证/状态/地址/标签/简介/建议/趋势/详情/网站仓库入口
 *   + 安装/卸载/停用/启用 + 命令复制）
 *
 * 与 Host 的通信走 Package-private RPC（host.call('nexus.*')），
 * Host 端实现见 src/index.js。
 */
module.exports = {
  apply(ctx) {
    const CATEGORY_META = {
      plugin: { label: '插件', color: '#3d7bff' },
      marketplace: { label: '插件市场', color: '#e0603f' },
      website: { label: '插件市场网站', color: '#1f9d62' },
      library: { label: '精选库', color: '#9a5cff' },
    }

    const STATUS_META = {
      active: { label: '正常', color: 'var(--dsw-alias-state-success-primary)' },
      inactive: { label: '已失效', color: 'var(--dsw-alias-state-error-primary)' },
      deprecated: { label: '已弃用', color: 'var(--dsw-alias-state-warn-primary)' },
    }

    const REFRESH_LABEL = { hourly: '每小时', daily: '每日', weekly: '每周' }
    const SOURCE_LABEL = { github_repo: 'GitHub 仓库', web_api: 'Web API', website: '网站' }
    const SORT_OPTIONS = [
      { id: 'stars', label: '★ 星数' },
      { id: 'items', label: '▣ 条目数' },
      { id: 'name', label: '名称' },
    ]

    const NAV_LINKS = [
      { label: 'DSH 官网', url: 'https://www.deepseek.com/harness' },
      { label: '插件目录 (topic)', url: 'https://github.com/topics/dsh-plugin' },
      { label: 'GitHub 搜索', url: 'https://github.com/search?q=dsh-plugin&type=repositories' },
    ]

    function shortDate(iso) {
      return iso ? String(iso).slice(0, 10) : '未知'
    }

    function trimUrl(url) {
      return String(url || '').replace(/^https?:\/\//, '')
    }

    function relativeTime(iso, now) {
      if (!iso) return '未知'
      const t = new Date(iso).getTime()
      if (isNaN(t)) return shortDate(iso)
      const diff = Math.max(0, now - t)
      const min = Math.floor(diff / 60000)
      if (min < 1) return '刚刚'
      if (min < 60) return min + ' 分钟前'
      const hr = Math.floor(min / 60)
      if (hr < 24) return hr + ' 小时前'
      const day = Math.floor(hr / 24)
      if (day < 30) return day + ' 天前'
      const mon = Math.floor(day / 30)
      if (mon < 12) return mon + ' 个月前'
      return Math.floor(mon / 12) + ' 年前'
    }

    function sinceLabel(iso, now) {
      if (!iso) return ''
      const t = new Date(iso).getTime()
      if (isNaN(t)) return ''
      const days = Math.floor(Math.max(0, now - t) / 86400000)
      if (days < 1) return '今天'
      if (days < 30) return days + ' 天'
      if (days < 365) return Math.floor(days / 30) + ' 个月'
      return Math.floor(days / 365) + ' 年'
    }

    function isSandboxError(raw) {
      const s = String(raw || '')
      return s.indexOf('sandbox') !== -1 || s.indexOf('CreateProcessAsUserW') !== -1 || s.indexOf('bubblewrap') !== -1 || s.indexOf('windows-acl') !== -1 || s.indexOf('Landlock') !== -1 || s.indexOf('sandbox-exec') !== -1
    }

    function friendlyError(raw) {
      const s = String(raw || '')
      if (isSandboxError(s)) {
        return '本机沙箱环境不可用（权限不足）：自动安装/卸载暂不可用。建议以管理员身份运行 DSH；或使用「复制命令」在终端手动操作；若信任当前环境，可在设置中切换沙箱模式为 danger-full-access（会降低命令隔离）。停用/启用不受影响。'
      }
      return s
    }

    const CSS = `
.nexus-root { display: flex; flex-direction: column; gap: 14px; padding: 4px 2px 24px; }
.nexus-btn { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 8px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-primary); font-size: 12px; cursor: pointer; text-decoration: none; }
.nexus-btn:hover { border-color: var(--dsw-alias-brand-primary); color: var(--dsw-alias-brand-primary); }
.nexus-btn-ghost { background: transparent; }
.nexus-btn-danger { border-color: var(--dsw-alias-state-error-primary); color: var(--dsw-alias-state-error-primary); background: transparent; }
.nexus-btn-danger:hover { background: var(--dsw-alias-state-error-primary); color: var(--dsw-alias-bg-base); border-color: var(--dsw-alias-state-error-primary); }
.nexus-navcard { display: flex; flex-direction: column; gap: 8px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); border-radius: 12px; padding: 12px 14px; }
.nexus-navcard-head { font-size: 12px; font-weight: 600; color: var(--dsw-alias-label-secondary); }
.nexus-navrow { display: flex; gap: 8px; flex-wrap: wrap; }
.nexus-navbtn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--dsw-alias-brand-primary); color: var(--dsw-alias-brand-primary); background: transparent; font-size: 12px; text-decoration: none; transition: background .15s, color .15s; }
.nexus-navbtn:hover { background: var(--dsw-alias-brand-primary); color: var(--dsw-alias-bg-base); }
.nexus-navarrow { font-size: 11px; opacity: .8; }
.nexus-more-card { padding: 0; }
.nexus-more-toggle { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 12px 14px; border: none; background: transparent; color: var(--dsw-alias-label-primary); font-size: 12px; font-weight: 600; cursor: pointer; border-radius: 12px; }
.nexus-more-toggle:hover { color: var(--dsw-alias-brand-primary); }
.nexus-more-caret { color: var(--dsw-alias-label-secondary); font-size: 11px; }
.nexus-more-body { display: flex; flex-direction: column; gap: 10px; padding: 0 14px 12px; border-top: 1px solid var(--dsw-alias-border-l1); padding-top: 10px; }
.nexus-env { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--dsw-alias-label-secondary); }
.nexus-env-row { display: flex; gap: 6px; line-height: 1.6; }
.nexus-env-label { color: var(--dsw-alias-label-primary); flex: none; min-width: 64px; }
.nexus-env-tip { display: flex; gap: 6px; line-height: 1.6; font-size: 11px; color: var(--dsw-alias-state-warn-primary); background: var(--dsw-alias-bg-layer-2); border: 1px dashed var(--dsw-alias-border-l2); border-radius: 8px; padding: 8px 10px; }
.nexus-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.nexus-chip { padding: 5px 12px; border-radius: 999px; border: 1px solid var(--dsw-alias-border-l2); background: transparent; color: var(--dsw-alias-label-secondary); font-size: 12px; cursor: pointer; }
.nexus-chip-on { border-color: var(--dsw-alias-brand-primary); color: var(--dsw-alias-brand-primary); background: var(--dsw-alias-bg-layer-2); }
.nexus-search { flex: 1; min-width: 160px; padding: 6px 10px; border-radius: 8px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-primary); font-size: 12px; outline: none; }
.nexus-search:focus { border-color: var(--dsw-alias-brand-primary); }
.nexus-sort { padding: 6px 8px; border-radius: 8px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-primary); font-size: 12px; outline: none; cursor: pointer; }
.nexus-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.nexus-card { display: flex; flex-direction: column; gap: 8px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); border-radius: 12px; padding: 14px; }
.nexus-card:hover { border-color: var(--dsw-alias-border-l2); }
.nexus-card-head { display: flex; align-items: flex-start; gap: 10px; }
.nexus-icon { width: 40px; height: 40px; border-radius: 9px; object-fit: cover; flex: none; background: var(--dsw-alias-bg-layer-2); }
.nexus-icon-fallback { width: 40px; height: 40px; border-radius: 9px; flex: none; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 700; color: var(--dsw-alias-brand-primary); background: var(--dsw-alias-bg-layer-2); }
.nexus-card-title { min-width: 0; flex: 1; }
.nexus-repo-card { position: relative; }
.nexus-repo-head { display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; }
.nexus-repo-head .nexus-icon, .nexus-repo-head .nexus-icon-fallback { width: 56px; height: 56px; border-radius: 12px; font-size: 22px; }
.nexus-repo-name-row { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 6px; }
.nexus-repo-card .nexus-card-name { font-size: 20px; font-weight: 700; }
.nexus-repo-subname { font-size: 14px; font-weight: 600; color: var(--dsw-alias-label-secondary); }
.nexus-repo-url-text { font-size: 11px; color: var(--dsw-alias-brand-primary); text-decoration: none; word-break: break-all; }
.nexus-repo-url-text:hover { text-decoration: underline; }
.nexus-repo-url-btn { position: absolute; top: 14px; right: 14px; }
.nexus-repo-card .nexus-card-tags { justify-content: center; }
.nexus-repo-card .nexus-card-desc { text-align: center; }
.nexus-repo-card .nexus-card-tip { text-align: center; }
.nexus-repo-card .nexus-card-meta { justify-content: center; }
.nexus-repo-card .nexus-repo-note { text-align: center; }
.nexus-repo-card .nexus-card-links { justify-content: center; }
.nexus-card-name-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.nexus-card-name { font-size: 14px; font-weight: 600; color: var(--dsw-alias-label-primary); }
.nexus-badge { font-size: 10px; padding: 1px 7px; border-radius: 999px; border: 1px solid; line-height: 1.6; white-space: nowrap; }
.nexus-status-badge { margin-left: auto; flex: none; }
.nexus-card-urls { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; align-items: center; }
.nexus-url { color: var(--dsw-alias-brand-primary); text-decoration: none; word-break: break-all; }
.nexus-url:hover { text-decoration: underline; }
.nexus-url-sep { color: var(--dsw-alias-label-secondary); }
.nexus-card-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.nexus-tag { font-size: 10px; padding: 2px 8px; border-radius: 6px; background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-secondary); }
.nexus-card-desc { font-size: 12px; color: var(--dsw-alias-label-secondary); line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.nexus-card-tip { font-size: 11px; color: var(--dsw-alias-state-warn-primary); line-height: 1.5; }
.nexus-card-meta { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding-top: 2px; }
.nexus-mi { display: flex; align-items: baseline; gap: 4px; font-size: 12px; color: var(--dsw-alias-label-primary); }
.nexus-mi-label { color: var(--dsw-alias-label-secondary); font-size: 11px; }
.nexus-delta { font-size: 11px; }
.nexus-delta-up { color: var(--dsw-alias-state-success-primary); }
.nexus-delta-down { color: var(--dsw-alias-state-error-primary); }
.nexus-btn-detail { margin-left: auto; }
.nexus-card-detail { display: flex; flex-direction: column; gap: 6px; background: var(--dsw-alias-bg-layer-2); border-radius: 8px; padding: 10px; font-size: 11px; animation: nexus-fade-in .18s ease; }
@keyframes nexus-fade-in { from { opacity: 0; transform: translateY(-2px); } to { opacity: 1; transform: none; } }
.nexus-detail-row { display: flex; gap: 6px; color: var(--dsw-alias-label-primary); line-height: 1.6; }
.nexus-detail-label { color: var(--dsw-alias-label-secondary); flex: none; min-width: 62px; }
.nexus-detail-note { color: var(--dsw-alias-label-secondary); line-height: 1.6; padding-left: 68px; }
.nexus-detail-warn { display: flex; gap: 6px; color: var(--dsw-alias-state-error-primary); line-height: 1.6; padding: 6px 8px; border: 1px dashed var(--dsw-alias-state-error-primary); border-radius: 6px; }
.nexus-card-links { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding-top: 2px; }
.nexus-install-inline { margin-left: auto; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11px; }
.nexus-installed-tag { color: var(--dsw-alias-state-success-primary); font-size: 11px; }
.nexus-disabled-tag { color: var(--dsw-alias-state-warn-primary); font-size: 11px; }
.nexus-install-msg { color: var(--dsw-alias-label-secondary); word-break: break-all; max-width: 100%; }
.nexus-install-msg-ok { color: var(--dsw-alias-state-success-primary); word-break: break-all; max-width: 100%; }
.nexus-install-msg-fail { color: var(--dsw-alias-state-error-primary); word-break: break-all; max-width: 100%; }
.nexus-install-result { padding-top: 6px; font-size: 11px; }
.nexus-cmd-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 6px; font-size: 11px; }
.nexus-cmd { font-family: ui-monospace, Consolas, monospace; font-size: 11px; color: var(--dsw-alias-label-primary); background: var(--dsw-alias-bg-layer-2); border: 1px solid var(--dsw-alias-border-l1); border-radius: 6px; padding: 4px 8px; word-break: break-all; user-select: all; }
.nexus-repo-note { font-size: 11px; color: var(--dsw-alias-label-secondary); line-height: 1.6; }
.nexus-repo-warn { font-size: 11px; color: var(--dsw-alias-state-error-primary); line-height: 1.6; }
.nexus-empty { padding: 40px 0; text-align: center; color: var(--dsw-alias-label-secondary); font-size: 13px; }
.nexus-error { padding: 24px; text-align: center; color: var(--dsw-alias-state-error-primary); font-size: 13px; border: 1px dashed var(--dsw-alias-state-error-primary); border-radius: 12px; }
.nexus-loading { padding: 40px 0; text-align: center; color: var(--dsw-alias-label-secondary); font-size: 13px; }
`

    function IconCell(props) {
      const [failed, setFailed] = React.useState(false)
      if (failed || !props.src) {
        return React.createElement('div', { className: 'nexus-icon-fallback' }, String(props.name || '?').charAt(0))
      }
      return React.createElement('img', {
        className: 'nexus-icon',
        src: props.src,
        alt: '',
        loading: 'lazy',
        onError: function () { setFailed(true) },
      })
    }

    function Delta(props) {
      if (props.value == null) return null
      const up = props.value >= 0
      return React.createElement('span', {
        className: up ? 'nexus-delta nexus-delta-up' : 'nexus-delta nexus-delta-down',
      }, (up ? '↑' : '↓') + Math.abs(props.value))
    }

    function metaCell(label, value, delta) {
      return React.createElement('div', { className: 'nexus-mi' },
        React.createElement('span', { className: 'nexus-mi-label' }, label),
        value != null ? String(value) : '未知',
        delta != null ? React.createElement(Delta, { value: delta }) : null,
      )
    }

    function detailRow(label, value, title) {
      return React.createElement('div', { className: 'nexus-detail-row' },
        React.createElement('span', { className: 'nexus-detail-label' }, label),
        React.createElement('span', { title: title || '' }, value),
      )
    }

    function navLinkEl(l) {
      return React.createElement('a', {
        key: l.url,
        className: 'nexus-navbtn',
        href: l.url,
        target: '_blank',
        rel: 'noopener noreferrer',
        title: l.url,
      },
        l.label,
        React.createElement('span', { className: 'nexus-navarrow' }, '→'),
      )
    }

    function envValue(e, key) {
      const v = e[key]
      const err = e[key + 'Error']
      if (v != null && v !== '') return v
      if (err) return '不可用'
      return '—'
    }

    function envTip(e) {
      const keys = ['platform', 'node', 'pnpm', 'npm', 'dsh']
      for (const k of keys) {
        if (e[k + 'Error']) return friendlyError(e[k + 'Error'])
      }
      return null
    }

    function MoreCard(props) {
      const [open, setOpen] = React.useState(false)
      const [env, setEnv] = React.useState(null)
      React.useEffect(function () {
        if (!open || env !== null) return
        host.call('nexus.env').then(function (res) {
          if (res && res.ok) setEnv(res.env)
          else setEnv({ error: (res && res.error) || '查询失败' })
        }).catch(function () { setEnv({ error: '查询失败' }) })
      }, [open])
      const e = env || {}
      const tip = envTip(e)
      const envBlock = React.createElement('div', { className: 'nexus-env' },
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, '工作区'), React.createElement('span', null, e.workspace || '—')),
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, 'Profile'), React.createElement('span', null, e.profile || '—')),
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, '平台'), React.createElement('span', { title: e.platformError || '' }, envValue(e, 'platform'))),
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, 'Node'), React.createElement('span', { title: e.nodeError || '' }, envValue(e, 'node'))),
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, 'pnpm'), React.createElement('span', { title: e.pnpmError || '' }, envValue(e, 'pnpm'))),
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, 'npm'), React.createElement('span', { title: e.npmError || '' }, envValue(e, 'npm'))),
        React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, 'dsh'), React.createElement('span', { title: e.dshError || '' }, envValue(e, 'dsh'))),
        tip ? React.createElement('div', { className: 'nexus-env-tip' }, tip) : null,
        e.error ? React.createElement('div', { className: 'nexus-env-row' }, React.createElement('span', { className: 'nexus-env-label' }, '提示'), React.createElement('span', null, e.error)) : null,
      )
      return React.createElement('div', { className: 'nexus-navcard nexus-more-card' },
        React.createElement('button', { className: 'nexus-more-toggle', onClick: function () { setOpen(!open) } },
          React.createElement('span', null, '更多'),
          React.createElement('span', { className: 'nexus-more-caret' }, open ? '▴' : '▾'),
        ),
        open ? React.createElement('div', { className: 'nexus-more-body' },
          React.createElement('div', { className: 'nexus-navcard-head' }, '生态导航'),
          React.createElement('div', { className: 'nexus-navrow' }, props.navLinks.map(navLinkEl)),
          React.createElement('div', { className: 'nexus-navcard-head' }, '本机环境'),
          envBlock,
        ) : null,
      )
    }

    function RepoCard(props) {
      const repo = props.repo
      const meta = props.meta
      const summary = props.summary
      const now = props.now
      if (!repo) return null
      const commitText = repo.commit ? String(repo.commit).slice(0, 7) : '未建仓'
      const hubStars = repo.hub_stars != null ? String(repo.hub_stars) : '未知'
      const hubDelta = repo.stars_delta != null ? repo.stars_delta : null
      const totalText = summary && summary.total_markets != null ? String(summary.total_markets) : '未知'
      const activeText = summary && summary.active_count != null ? String(summary.active_count) : '未知'
      const inactiveText = summary && summary.inactive_count != null ? String(summary.inactive_count) : '未知'
      const relUpdate = meta && meta.generated_at ? relativeTime(meta.generated_at, now) : ''
      const relCheck = summary && summary.last_check ? relativeTime(summary.last_check, now) : ''
      const expired = meta && meta.valid_until ? now > new Date(meta.valid_until).getTime() : false
      const metaNote = meta && meta.generated_at
        ? '更新于 ' + relUpdate + '（' + String(meta.generated_at).slice(0, 16).replace('T', ' ') + '） · Schema ' + (meta.schema_version || '') + (meta.valid_until ? ' · 缓存至 ' + String(meta.valid_until).slice(0, 10) : '') + (relCheck ? ' · 上次巡检 ' + relCheck : '')
        : ''
      const repoLinks = [
        repo.homepage ? { url: repo.homepage, label: '官网' } : null,
        repo.docs ? { url: repo.docs, label: '文档' } : null,
      ].filter(Boolean)
      return React.createElement('div', { className: 'nexus-card nexus-repo-card' },
        repo.url
          ? React.createElement('a', { className: 'nexus-btn nexus-repo-url-btn', href: repo.url, target: '_blank', rel: 'noopener noreferrer' }, '枢纽仓库')
          : null,
        React.createElement('div', { className: 'nexus-repo-head' },
          repo.icon
            ? React.createElement(IconCell, { src: repo.icon, name: repo.display_name || 'DSH 万市枢纽' })
            : React.createElement('div', { className: 'nexus-icon-fallback' }, '枢'),
          React.createElement('div', { className: 'nexus-repo-name-row' },
            React.createElement('span', { className: 'nexus-card-name' }, repo.display_name || 'DSH 万市枢纽'),
          ),
          repo.name
            ? React.createElement('div', { className: 'nexus-repo-subname' }, repo.name)
            : null,
          repo.url
            ? React.createElement('a', { className: 'nexus-repo-url-text', href: repo.url, target: '_blank', rel: 'noopener noreferrer' }, trimUrl(repo.url))
            : null,
        ),
        (repo.tags && repo.tags.length)
          ? React.createElement('div', { className: 'nexus-card-tags' }, repo.tags.map(function (t) {
              return React.createElement('span', { className: 'nexus-tag', key: t }, t)
            }))
          : null,
        repo.description ? React.createElement('div', { className: 'nexus-card-desc' }, repo.description) : null,
        repo.usage_tip ? React.createElement('div', { className: 'nexus-card-tip' }, '标注：' + repo.usage_tip) : null,
        React.createElement('div', { className: 'nexus-card-meta' },
          metaCell('★', hubStars, hubDelta),
          metaCell('▣', totalText, null),
          metaCell('●', activeText + ' 正常', null),
          metaCell('‖', inactiveText + ' 失效', null),
          metaCell('◈', repo.branch || '—', null),
          metaCell('◆', commitText, null),
          repo.maintainer ? metaCell('维护', repo.maintainer, null) : null,
        ),
        metaNote ? React.createElement('div', { className: 'nexus-repo-note' }, metaNote) : null,
        expired ? React.createElement('div', { className: 'nexus-repo-warn' }, '数据已过期，请点击刷新获取最新数据') : null,
        props.source ? React.createElement('div', { className: 'nexus-repo-note' }, '数据源：' + props.source) : null,
        repoLinks.length ? React.createElement('div', { className: 'nexus-card-links' },
          repoLinks.map(function (l) {
            return React.createElement('a', { key: l.url, className: 'nexus-btn' + (l.label !== '枢纽仓库' ? ' nexus-btn-ghost' : ''), href: l.url, target: '_blank', rel: 'noopener noreferrer' }, l.label)
          }),
        ) : null,
      )
    }

    function MarketCard(props) {
      const m = props.market
      const now = props.now
      const deps = props.deps || []
      const bundles = props.bundles || []
      const [open, setOpen] = React.useState(false)
      const [act, setAct] = React.useState(null)
      const [showCmd, setShowCmd] = React.useState(false)
      const [copied, setCopied] = React.useState(false)
      const [version, setVersion] = React.useState(null)
      const [versionState, setVersionState] = React.useState('idle')
      const statusMeta = STATUS_META[m.status] || { label: String(m.status), color: '#7c8699' }

      const isGithubHome = String(m.homepage || '').indexOf('github.com') !== -1
      const repoId = m.data_source && m.data_source.type === 'github_repo' ? m.data_source.identifier : null
      const repoUrl = repoId ? 'https://github.com/' + repoId : null
      const siteUrl = m.homepage && !isGithubHome ? m.homepage : null
      const spec = m.npm_package || (repoId ? 'github:' + repoId : null)
      const installable = spec && (m.categories || []).some(function (c) { return c === 'plugin' || c === 'marketplace' })
      const installed = installable && deps.some(function (d) {
        const dv = String(d.value || '')
        if (m.npm_package && (d.name === m.npm_package || d.name.indexOf(m.npm_package) !== -1 || dv.indexOf(m.npm_package) !== -1)) return true
        if (repoId && (d.name.indexOf(repoId) !== -1 || dv.indexOf(repoId) !== -1)) return true
        return false
      })
      const enabled = installed && bundles.some(function (b) {
        if (m.npm_package && b === m.npm_package) return true
        if (repoId && (b.indexOf(repoId) !== -1 || repoId.indexOf(b) !== -1)) return true
        return false
      })
      const installCmd = 'dsh plugin --profile web add ' + spec
      const removeCmd = 'dsh plugin --profile web remove ' + spec

      React.useEffect(function () {
        if (!open || !installable || !m.npm_package || versionState !== 'idle') return
        setVersionState('loading')
        host.call('nexus.latest', { pkg: m.npm_package }).then(function (res) {
          if (res && res.ok) setVersion(res.version)
          setVersionState('done')
        }).catch(function () { setVersionState('done') })
      }, [open])

      const copyText = function (text) {
        try {
          if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            navigator.clipboard.writeText(text).then(function () { setCopied(true) }).catch(function () { setCopied(false) })
          } else {
            setCopied(false)
          }
        } catch (e) {
          setCopied(false)
        }
      }

      const stars = m.popularity && m.popularity.github_stars != null ? m.popularity.github_stars : null
      const starsDelta = m.popularity && m.popularity.stars_delta != null ? m.popularity.stars_delta : null
      const items = m.item_count != null ? m.item_count : null
      const itemsDelta = m.item_count_delta != null ? m.item_count_delta : null
      const refreshLabel = REFRESH_LABEL[m.refresh_interval] || (m.refresh_interval || '未知')
      const sourceLabel = SOURCE_LABEL[m.data_source && m.data_source.type] || (m.data_source && m.data_source.type) || '未知'
      const sourceId = m.data_source && m.data_source.identifier ? m.data_source.identifier : null
      const upstreams = m.upstream_sources && m.upstream_sources.length ? m.upstream_sources : null
      const lastSync = m.data_source ? m.data_source.last_sync : null
      const since = sinceLabel(m.first_added, now)

      const catBadges = (m.categories || []).map(function (c) {
        const meta = CATEGORY_META[c]
        return meta
          ? React.createElement('span', { key: c, className: 'nexus-badge', style: { color: meta.color, borderColor: meta.color } }, meta.label)
          : null
      })

      const urlRow = (siteUrl || repoUrl)
        ? React.createElement('div', { className: 'nexus-card-urls' },
            siteUrl ? React.createElement('a', { className: 'nexus-url', href: siteUrl, target: '_blank', rel: 'noopener noreferrer' }, trimUrl(siteUrl)) : null,
            siteUrl && repoUrl ? React.createElement('span', { className: 'nexus-url-sep' }, ' · ') : null,
            repoUrl ? React.createElement('a', { className: 'nexus-url', href: repoUrl, target: '_blank', rel: 'noopener noreferrer' }, trimUrl(repoUrl)) : null,
          )
        : null

      const runAction = function (kind) {
        setAct({ phase: 'running', kind: kind, msg: '' })
        const call = kind === 'install' ? 'nexus.install' : (kind === 'uninstall' ? 'nexus.uninstall' : 'nexus.setEnabled')
        const args = kind === 'enable' || kind === 'disable' ? { spec: spec, enabled: kind === 'enable' } : { spec: spec }
        host.call(call, args).then(function (res) {
          if (res && res.ok) {
            const label = kind === 'install' ? '安装成功' : (kind === 'uninstall' ? '已卸载' : (kind === 'enable' ? '已启用' : '已停用'))
            setAct({ phase: 'result', kind: kind, ok: true, msg: label + '，重启 DSH 后生效' + (res.note ? '（' + res.note + '）' : '') })
          } else {
            setAct({ phase: 'result', kind: kind, ok: false, msg: friendlyError(res && (res.err || res.error)) })
          }
        }).catch(function (err) {
          setAct({ phase: 'result', kind: kind, ok: false, msg: friendlyError((err && err.message) || err) })
        })
      }

      let installInline = null
      if (installable) {
        let controls
        if (act && act.phase === 'confirm') {
          const actLabel = act.kind === 'install' ? '安装' : (act.kind === 'uninstall' ? '卸载' : (act.kind === 'enable' ? '启用' : '停用'))
          controls = React.createElement(React.Fragment, null,
            React.createElement('span', { className: 'nexus-install-msg' }, '确认' + actLabel + ' ' + spec + ' ？'),
            React.createElement('button', { className: 'nexus-btn', onClick: function () { runAction(act.kind) } }, '确认'),
            React.createElement('button', { className: 'nexus-btn nexus-btn-ghost', onClick: function () { setAct(null) } }, '取消'),
          )
        } else if (act && act.phase === 'running') {
          const actLabel = act.kind === 'install' ? '安装' : (act.kind === 'uninstall' ? '卸载' : (act.kind === 'enable' ? '启用' : '停用'))
          controls = React.createElement('span', { className: 'nexus-install-msg' }, '正在' + actLabel + '，请稍候…')
        } else {
          controls = React.createElement(React.Fragment, null,
            installed && enabled ? React.createElement('span', { className: 'nexus-installed-tag' }, '✓ 已安装') : null,
            installed && !enabled ? React.createElement('span', { className: 'nexus-disabled-tag' }, '‖ 已停用') : null,
            installed
              ? React.createElement(React.Fragment, null,
                  React.createElement('button', { className: 'nexus-btn', onClick: function () { setAct({ phase: 'confirm', kind: enabled ? 'disable' : 'enable', msg: '' }) } }, enabled ? '停用' : '启用'),
                  React.createElement('button', { className: 'nexus-btn nexus-btn-danger', onClick: function () { setAct({ phase: 'confirm', kind: 'uninstall', msg: '' }) } }, '卸载'),
                )
              : React.createElement('button', { className: 'nexus-btn', onClick: function () { setAct({ phase: 'confirm', kind: 'install', msg: '' }) } }, '安装'),
            React.createElement('button', { className: 'nexus-btn nexus-btn-ghost', onClick: function () { setShowCmd(!showCmd); setCopied(false) } }, '命令'),
          )
        }
        installInline = React.createElement('span', { className: 'nexus-install-inline' }, controls)
      }

      const detail = open ? React.createElement('div', { className: 'nexus-card-detail' },
        m.security_note ? React.createElement('div', { className: 'nexus-detail-warn' }, '安全提示：' + m.security_note) : null,
        m.status_message ? detailRow('状态', m.status_message) : null,
        m.popularity && m.popularity.rank != null ? detailRow('排名', '#' + m.popularity.rank) : null,
        detailRow('数据源', sourceLabel + (sourceId ? ' · ' + sourceId : '')),
        detailRow('上次同步', relativeTime(lastSync, now), lastSync || ''),
        detailRow('巡检时间', relativeTime(m.last_check, now), m.last_check || ''),
        detailRow('更新频率', refreshLabel),
        detailRow('内容更新', relativeTime(m.last_plugin_update, now), m.last_plugin_update || ''),
        detailRow('收录时间', shortDate(m.first_added) + (since ? '（已收录 ' + since + '）' : ''), m.first_added || ''),
        installable && m.npm_package ? detailRow('最新版本', versionState === 'loading' ? '查询中…' : (version || '查询失败'), 'npm: ' + m.npm_package) : null,
        m.environment ? detailRow('环境要求', m.environment) : null,
        upstreams ? detailRow('上游源', upstreams.join(' · ')) : null,
      ) : null

      return React.createElement('div', { className: 'nexus-card' },
        React.createElement('div', { className: 'nexus-card-head' },
          React.createElement(IconCell, { src: m.icon, name: m.name }),
          React.createElement('div', { className: 'nexus-card-title' },
            React.createElement('div', { className: 'nexus-card-name-row' },
              React.createElement('span', { className: 'nexus-card-name', title: m.name }, m.name),
              catBadges,
            ),
            urlRow,
          ),
          React.createElement('span', { className: 'nexus-badge nexus-status-badge', style: { color: statusMeta.color, borderColor: statusMeta.color } }, statusMeta.label),
        ),
        (m.tags && m.tags.length)
          ? React.createElement('div', { className: 'nexus-card-tags' }, m.tags.map(function (t) {
              return React.createElement('span', { className: 'nexus-tag', key: t }, t)
            }))
          : null,
        React.createElement('div', { className: 'nexus-card-desc' }, m.description),
        m.usage_tip ? React.createElement('div', { className: 'nexus-card-tip' }, '标注：' + m.usage_tip) : null,
        React.createElement('div', { className: 'nexus-card-meta' },
          metaCell('★', stars, starsDelta),
          metaCell('▣', items, itemsDelta),
          metaCell('↻', refreshLabel, null),
          React.createElement('button', { className: 'nexus-btn nexus-btn-ghost nexus-btn-detail', onClick: function () { setOpen(!open) } }, open ? '收起 ▴' : '详情 ▾'),
        ),
        detail,
        React.createElement('div', { className: 'nexus-card-links' },
          siteUrl ? React.createElement('a', { className: 'nexus-btn', href: siteUrl, target: '_blank', rel: 'noopener noreferrer' }, '访问市场网站') : null,
          repoUrl ? React.createElement('a', { className: 'nexus-btn nexus-btn-ghost', href: repoUrl, target: '_blank', rel: 'noopener noreferrer' }, 'GitHub 仓库') : null,
          installInline,
        ),
        showCmd && installable ? React.createElement('div', { className: 'nexus-cmd-row' },
          installed
            ? React.createElement(React.Fragment, null,
                React.createElement('code', { className: 'nexus-cmd' }, removeCmd),
                React.createElement('button', { className: 'nexus-btn', onClick: function () { copyText(removeCmd) } }, copied ? '已复制' : '复制卸载'),
                React.createElement('span', { className: 'nexus-install-msg' }, '停用/启用：请在面板使用按钮（需重启 DSH 生效）'),
              )
            : React.createElement(React.Fragment, null,
                React.createElement('code', { className: 'nexus-cmd' }, installCmd),
                React.createElement('button', { className: 'nexus-btn', onClick: function () { copyText(installCmd) } }, copied ? '已复制' : '复制安装'),
                React.createElement('span', { className: 'nexus-install-msg' }, '在终端中运行即可手动安装（需重启 DSH 生效）'),
              ),
        ) : null,
        act && act.phase === 'result'
          ? React.createElement('div', { className: 'nexus-install-result' }, React.createElement('span', { className: act.ok ? 'nexus-install-msg-ok' : 'nexus-install-msg-fail' }, act.msg))
          : null,
      )
    }

    function NexusPanel() {
      const [result, setResult] = React.useState({ phase: 'loading', data: null, error: null, source: null })
      const [deps, setDeps] = React.useState([])
      const [bundles, setBundles] = React.useState([])
      const [tick, setTick] = React.useState(0)
      const [catFilter, setCatFilter] = React.useState('all')
      const [inputValue, setInputValue] = React.useState('')
      const [activeQuery, setActiveQuery] = React.useState('')
      const [sortKey, setSortKey] = React.useState('stars')

      React.useEffect(function () {
        let alive = true
        host.call('nexus.load').then(function (res) {
          if (!alive) return
          if (res && res.ok) {
            setResult({ phase: 'ready', data: res.data, error: null, source: res.source })
          } else {
            setResult({ phase: 'error', data: null, error: (res && res.error) || '加载失败', source: null })
          }
        }).catch(function (err) {
          if (!alive) return
          setResult({ phase: 'error', data: null, error: String((err && err.message) || err), source: null })
        })
        return function () { alive = false }
      }, [tick])

      React.useEffect(function () {
        let alive = true
        host.call('nexus.installed').then(function (res) {
          if (!alive) return
          if (res && res.ok) {
            if (Array.isArray(res.deps)) setDeps(res.deps)
            if (Array.isArray(res.bundles)) setBundles(res.bundles)
          }
        }).catch(function () {})
        return function () { alive = false }
      }, [tick])

      const now = Date.now()
      const summary = result.data ? result.data.summary : null
      const markets = result.data ? (result.data.markets || []) : []
      const repo = result.data ? result.data.repo : null
      const meta = result.data ? result.data.file_meta : null
      const q = activeQuery.trim().toLowerCase()
      let filtered = markets.filter(function (m) {
        if (catFilter !== 'all' && (m.categories || []).indexOf(catFilter) === -1) return false
        if (q) {
          const hay = ((m.name || '') + ' ' + (m.description || '') + ' ' + (m.tags || []).join(' ')).toLowerCase()
          if (hay.indexOf(q) === -1) return false
        }
        return true
      })
      if (sortKey === 'stars') {
        filtered = filtered.slice().sort(function (a, b) { return ((b.popularity && b.popularity.github_stars) || 0) - ((a.popularity && a.popularity.github_stars) || 0) })
      } else if (sortKey === 'items') {
        filtered = filtered.slice().sort(function (a, b) { return (b.item_count || 0) - (a.item_count || 0) })
      } else if (sortKey === 'name') {
        filtered = filtered.slice().sort(function (a, b) { return String(a.name || '').localeCompare(String(b.name || ''), 'zh') })
      }

      const byCat = summary && summary.by_category ? summary.by_category : {}
      const chips = [
        { id: 'all', label: '全部 (' + markets.length + ')' },
        { id: 'plugin', label: '插件 (' + (byCat.plugin || 0) + ')' },
        { id: 'marketplace', label: '插件市场 (' + (byCat.marketplace || 0) + ')' },
        { id: 'website', label: '网站 (' + (byCat.website || 0) + ')' },
        { id: 'library', label: '精选库 (' + (byCat.library || 0) + ')' },
      ]

      const chipRow = chips.map(function (c) {
        return React.createElement('button', {
          key: c.id,
          className: catFilter === c.id ? 'nexus-chip nexus-chip-on' : 'nexus-chip',
          onClick: function () { setCatFilter(c.id) },
        }, c.label)
      })

      return React.createElement('div', { className: 'nexus-root' },
        React.createElement(RepoCard, { repo: repo, meta: meta, summary: summary, source: result.source, now: now }),
        React.createElement(MoreCard, { navLinks: NAV_LINKS }),
        React.createElement('div', { className: 'nexus-toolbar' },
          chipRow,
          React.createElement('input', {
            className: 'nexus-search',
            placeholder: '搜索名称 / 描述 / 标签…',
            value: inputValue,
            onChange: function (e) { setInputValue(e.target.value) },
            onKeyDown: function (e) { if (e.key === 'Enter') setActiveQuery(inputValue.trim()) },
          }),
          React.createElement('button', { className: 'nexus-btn', onClick: function () { setActiveQuery(inputValue.trim()) } }, '搜索'),
          activeQuery ? React.createElement('button', { className: 'nexus-btn nexus-btn-ghost', onClick: function () { setInputValue(''); setActiveQuery('') } }, '清除') : null,
          React.createElement('select', {
            className: 'nexus-sort',
            value: sortKey,
            onChange: function (e) { setSortKey(e.target.value) },
          }, SORT_OPTIONS.map(function (o) {
            return React.createElement('option', { key: o.id, value: o.id }, o.label)
          })),
          React.createElement('button', { className: 'nexus-btn', onClick: function () { setTick(tick + 1) } }, '刷新'),
        ),
        result.phase === 'error'
          ? React.createElement('div', { className: 'nexus-error' }, '加载失败：' + result.error)
          : filtered.length === 0
            ? React.createElement('div', { className: 'nexus-empty' }, result.phase === 'loading' ? '正在加载市场数据…' : '没有匹配的市场')
            : React.createElement('div', { className: 'nexus-grid' }, filtered.map(function (m) {
                return React.createElement(MarketCard, { market: m, key: m.id, now: now, deps: deps, bundles: bundles })
              })),
      )
    }

    const slots = ctx.get('slots')
    if (slots === undefined) return
    styles.insert(CSS)
    slots.inject('settings.section', function () {
      return slots.register(
        { name: 'settings.section', id: 'marketplaces-nexus', order: 30, label: '万市枢纽' },
        function () { return React.createElement(NexusPanel) },
      )
    })
  },
}
