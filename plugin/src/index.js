/**
 * DSH 万市枢纽 —— Host 侧插件（npm 发布版，标准 Cordis API）
 *
 * 发布版为「纯 Client 插件」：数据由 client 端直接 fetch 远程 raw，
 * 安装管理降级为命令复制，因此 Host 侧无需任何逻辑（空插件即可）。
 *
 * 开发版（动态插件 nexus-1 / 完整 host）见仓库历史与 collector 文档。
 */

module.exports = {
  name: 'dsh-marketplaces-nexus',
  config: {},
  apply(ctx) {
    // 空实现：面板功能全部在 client 侧（slots.inject('settings.section')）
  },
}
