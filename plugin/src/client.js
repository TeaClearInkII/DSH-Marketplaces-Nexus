/**
 * DSH 万市枢纽 —— Client 侧插件（npm 发布版，标准 Cordis API）
 *
 * 在 DSH Web 设置页注册「万市枢纽」页面（settings.section）：
 * 数据多级兜底获取（jsDelivr CDN → GitHub API → raw，均允许 CORS），
 * 配合本地缓存（stale-while-revalidate）：先渲染缓存秒开，后台静默刷新，
 * 全部源失败时回落缓存，不依赖 host RPC / 动态插件 API，保证任何环境可加载。
 *
 * 安装管理降级为「显示安装命令 + 复制」（本机安装请用 dsh plugin 命令）。
 *
 * bundle 格式与官方客户端插件一致：window.__ModuleLoader__.load(...)，
 * id 必须是包名（client-modules 以包名作为 graph row id）。
 */

window.__ModuleLoader__.load({
  id: 'dsh-marketplaces-nexus',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })
    const React = require('react')
    const name = 'nexus-market-panel'
    const inject = ['slots']
    function apply(ctx) {
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

    // 数据源：多级兜底（jsDelivr CDN 主 → GitHub API 实时 → raw 最后兜底；均可被 config 的 dataUrl 覆盖）
    // 本地缓存 + 后台刷新（stale-while-revalidate）：打开面板先渲染缓存，网络失败时回落缓存不报错
    const REMOTE_DATA_SOURCES = [
      { name: 'jsDelivr', kind: 'json', url: 'https://cdn.jsdelivr.net/gh/TeaClearInkII/DSH-Marketplaces-Nexus@main/docs/marketplaces.json' },
      { name: 'GitHub API', kind: 'base64', url: 'https://api.github.com/repos/TeaClearInkII/DSH-Marketplaces-Nexus/contents/docs/marketplaces.json' },
      { name: 'raw', kind: 'json', url: 'https://raw.githubusercontent.com/TeaClearInkII/DSH-Marketplaces-Nexus/main/docs/marketplaces.json' },
    ]
    const CACHE_KEY = 'nexus_marketplaces_v1'

    function loadCached() {
      try {
        const raw = localStorage.getItem(CACHE_KEY)
        if (!raw) return null
        const obj = JSON.parse(raw)
        return obj && obj.data ? obj : null
      } catch (e) {
        return null
      }
    }

    function saveCache(data) {
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), data: data }))
      } catch (e) {
        // 存储不可用时静默（无缓存不影响功能）
      }
    }

    function fetchRemote(done) {
      var queue = REMOTE_DATA_SOURCES.slice()
      var attempt = function (idx) {
        if (idx >= queue.length) {
          const cached = loadCached()
          done(cached
            ? { phase: 'ready', data: cached.data, error: '所有数据源均不可用', source: '缓存', fromCache: true, ts: cached.ts }
            : { phase: 'error', data: null, error: '所有数据源均不可用（jsDelivr / GitHub API / raw）', source: null, fromCache: false })
          return
        }
        const src = queue[idx]
        fetch(src.url)
          .then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status)
            return res.json()
          })
          .then(function (raw) {
            let data = raw
            if (src.kind === 'base64') {
              const b64 = String((raw && raw.content) || '').replace(/\s+/g, '')
              data = JSON.parse(decodeURIComponent(escape(atob(b64))))
            }
            if (!data || !data.markets) throw new Error('数据格式异常')
            saveCache(data)
            done({ phase: 'ready', data: data, error: null, source: src.name, fromCache: false, ts: Date.now() })
          })
          .catch(function () { attempt(idx + 1) })
      }
      attempt(0)
    }

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

    const CSS = `
.nexus-root { display: flex; flex-direction: column; gap: 14px; padding: 4px 2px 24px; }
.nexus-btn { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 8px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-primary); font-size: 12px; cursor: pointer; text-decoration: none; }
.nexus-btn:hover { border-color: var(--dsw-alias-brand-primary); color: var(--dsw-alias-brand-primary); }
.nexus-btn-ghost { background: transparent; }
.nexus-navcard { display: flex; flex-direction: column; gap: 8px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); border-radius: 12px; padding: 12px 14px; }
.nexus-navcard-head { font-size: 12px; font-weight: 600; color: var(--dsw-alias-label-secondary); text-align: center; }
.nexus-navrow { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.nexus-navbtn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--dsw-alias-brand-primary); color: var(--dsw-alias-brand-primary); background: transparent; font-size: 12px; text-decoration: none; transition: background .15s, color .15s; }
.nexus-navbtn:hover { background: var(--dsw-alias-brand-primary); color: var(--dsw-alias-bg-base); }
.nexus-navarrow { font-size: 11px; opacity: .8; }
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
.nexus-repo-head { display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center; }
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

    function MoreCard(props) {
      return React.createElement('div', { className: 'nexus-navcard' },
        React.createElement('div', { className: 'nexus-navcard-head' }, '生态导航'),
        React.createElement('div', { className: 'nexus-navrow' }, props.navLinks.map(navLinkEl)),
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
          repo.name ? React.createElement('div', { className: 'nexus-repo-subname' }, repo.name) : null,
          repo.url ? React.createElement('a', { className: 'nexus-repo-url-text', href: repo.url, target: '_blank', rel: 'noopener noreferrer' }, trimUrl(repo.url)) : null,
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
        repoLinks.length ? React.createElement('div', { className: 'nexus-card-links' },
          repoLinks.map(function (l) {
            return React.createElement('a', { key: l.url, className: 'nexus-btn nexus-btn-ghost', href: l.url, target: '_blank', rel: 'noopener noreferrer' }, l.label)
          }),
        ) : null,
      )
    }

    function MarketCard(props) {
      const m = props.market
      const now = props.now
      const [open, setOpen] = React.useState(false)
      const [showCmd, setShowCmd] = React.useState(false)
      const [copied, setCopied] = React.useState(false)
      const statusMeta = STATUS_META[m.status] || { label: String(m.status), color: '#7c8699' }

      const isGithubHome = String(m.homepage || '').indexOf('github.com') !== -1
      const repoId = m.data_source && m.data_source.type === 'github_repo' ? m.data_source.identifier : null
      const repoUrl = repoId ? 'https://github.com/' + repoId : null
      const siteUrl = m.homepage && !isGithubHome ? m.homepage : null
      const spec = m.npm_package || (repoId ? 'github:' + repoId : null)
      const installable = spec && (m.categories || []).some(function (c) { return c === 'plugin' || c === 'marketplace' })
      const installCmd = installable ? 'dsh plugin --profile web add ' + spec : null

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
          installable && installCmd
            ? React.createElement('span', { className: 'nexus-install-inline' },
                React.createElement('button', { className: 'nexus-btn nexus-btn-ghost', onClick: function () { setShowCmd(!showCmd); setCopied(false) } }, '安装命令'),
              )
            : null,
        ),
        showCmd && installCmd ? React.createElement('div', { className: 'nexus-cmd-row' },
          React.createElement('code', { className: 'nexus-cmd' }, installCmd),
          React.createElement('button', { className: 'nexus-btn', onClick: function () { copyText(installCmd) } }, copied ? '已复制' : '复制'),
          React.createElement('span', { className: 'nexus-install-inline' }, '在终端运行即可安装（安装后重启 DSH 生效）'),
        ) : null,
      )
    }

    function NexusPanel() {
      const [result, setResult] = React.useState(function () {
        const cached = loadCached()
        return cached
          ? { phase: 'ready', data: cached.data, error: null, source: '缓存', fromCache: true, ts: cached.ts }
          : { phase: 'loading', data: null, error: null, source: null, fromCache: false, ts: null }
      })
      const [tick, setTick] = React.useState(0)
      const [catFilter, setCatFilter] = React.useState('all')
      const [inputValue, setInputValue] = React.useState('')
      const [activeQuery, setActiveQuery] = React.useState('')
      const [sortKey, setSortKey] = React.useState('stars')

      React.useEffect(function () {
        let alive = true
        fetchRemote(function (r) { if (alive) setResult(r) })
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

      let statusLine = ''
      if (result.fromCache) {
        statusLine = '当前显示本地缓存（更新于 ' + (result.ts ? shortDate(result.ts) : '未知') + '）' + (result.error ? '；最新数据加载失败：' + result.error + '，点击「刷新」重试' : '；正在后台刷新…')
      } else if (result.source) {
        statusLine = '数据源：' + result.source
      } else if (result.phase === 'loading') {
        statusLine = '正在加载市场数据…'
      }

      return React.createElement('div', { className: 'nexus-root' },
        React.createElement(RepoCard, { repo: repo, meta: meta, summary: summary, now: now }),
        statusLine ? React.createElement('div', { className: 'nexus-repo-note', style: { textAlign: 'center' } }, statusLine) : null,
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
          ? React.createElement('div', { className: 'nexus-error' }, '加载失败：' + result.error + '（已尝试 ' + REMOTE_DATA_SOURCES.map(function (s) { return s.name }).join(' / ') + '，请检查网络/代理后点击「刷新」重试）')
          : result.phase === 'loading'
            ? React.createElement('div', { className: 'nexus-loading' }, '正在加载市场数据…')
            : filtered.length === 0
              ? React.createElement('div', { className: 'nexus-empty' }, '没有匹配的市场')
              : React.createElement('div', { className: 'nexus-grid' }, filtered.map(function (m) {
                  return React.createElement(MarketCard, { market: m, key: m.id, now: now })
                })),
      )
    }

    const slots = ctx.get('slots')
    if (slots === undefined) return
    // CSS 注入：用纯 DOM（不依赖 styles 全局，保证标准 bundle 环境可用）
    try {
      const styleEl = document.createElement('style')
      styleEl.textContent = CSS
      document.head.appendChild(styleEl)
    } catch (e) {
      // document 不可用时静默（样式缺失不影响功能）
    }
    slots.inject('settings.section', function () {
      return slots.register(
        { name: 'settings.section', id: 'marketplaces-nexus', order: 30, label: '万市枢纽' },
        function () { return React.createElement(NexusPanel) },
      )
    })
  }
    exports.apply = apply
    exports.inject = inject
    exports.name = name
    return module.exports
  }
})
