# Charge Tally

[English](README.md)

Charge Tally 读取 Home Assistant 中的电量、功率和电价实体，为多个充电点生成带共享身份的充电记录，提供实时统计、历史补录、修订和本地看板卡片。开始/结束动作只控制记账；读卡器、按钮和充电设备由你自己的 HA 自动化连接。

版本 **0.1.0** 的兼容与测试基线是 **Home Assistant 2026.9.1**，Linux 测试环境使用 **Python 3.14.7**。尚未认证更高 HA 版本。集成没有额外的第三方 Python 运行依赖，前端不使用 CDN 或远程运行依赖。

## 安装

手动安装：把 `dist/charge_tally-0.1.0.zip` 解压到 HA 配置目录，确认最终路径是 `<config>/custom_components/charge_tally/manifest.json`，不要多套一层压缩包名称目录。随后重启 Home Assistant。

HACS 分发：把 `https://github.com/enecess/ha-charge-tally` 添加为 **Integration** 类别的自定义仓库，下载 Charge Tally 后重启 HA。仓库提供 HACS 元数据，不表示已经进入 HACS 默认目录。HACS 从仓库安装集成目录，单独生成的 ZIP 用于手动安装。

进入 **设置 → 设备与服务 → 集成 → 添加集成 → Charge Tally**，确认账本币种；首次添加后自动进入第一个充电点配置。打开 Charge Tally 主集成可继续添加/重新配置充电点和共享身份。一个 HA 实例只支持一个主账本。账本永久绑定已确认币种，删除并重建集成后仍保留。配置流程复用保留币种并拒绝其他币种，不提供汇率转换。对于已有数据但未绑定币种的预发布账本，必须先备份并明确确认原币种才能加载，绝不静默更换历史金额的币种标签。

## 三种输入与三种电价

| 输入模式 | 计量来源 | 自动识别 |
| --- | --- | --- |
| 仅电量 | 累计 Wh/kWh/MWh 实体，状态类别为 `total` 或 `total_increasing` | 不提供，使用手动动作 |
| 仅功率 | W/kW 实体 → 集成管理的原生 HA Integral，左矩形法、小时单位、最大子间隔 **60 秒** | 可选 |
| 电量加功率 | 电量用于记账；功率用于识别和显示 | 可选；不会把功率重复积分计量 |

输入应代表充电回路。“每次上报一段电量”不等于累计表底。首次有效读数只建立基准，不把原有表底记为新增用电。负功率、负电量、错误单位、未知或不可用状态都不是有效的零用电。同一源实体被重复选为多个点会被拒绝。

可配置“表底可能重置”：允许下降时仅计入能确认的重置后电量，并标记重置区间不完整；不允许下降时暂停差分，等待有效基准恢复。原生 Integral 和日/月/年 Utility Meter 通过 HA 配置流程创建，不要改作其他用途。受管理辅助元素被删除或修改时，充电点产生修复提示，需明确确认修复才重建；外部源实体不会被删除。

| 电价模式 | 规则 |
| --- | --- |
| 固定单价 | 每 kWh 单价；修改生成新的生效版本 |
| 动态实体 | 实际观测到的“账本币种/Wh、/kWh、/MWh”状态；缺少单位时需明确确认 |
| 每日分时 | 每天重复完整覆盖一天的时刻表，支持跨午夜；不能有空白或重叠，日末填写 `24:00` |

零价和负价合法。动态价格无效/不可用会结束上一有效价格，不会无限沿用。未知费用显示“已知小计 · 待补充”，不当作完整零费用。不解释供应商的未来价格属性或迟到价格的真实生效时刻，不支持汇率、星期、节假日或季节时刻表。

## 记录、身份与估算口径

身份在所有充电点之间共享，使用稳定 ID，改名不改变历史关联。停用/删除身份保留历史；新建同名身份不会接管旧 ID。每点独立选择下次身份，内置 **未分配**，无需先创建身份即可记账。手动开始可以覆盖本次身份，不改变下次选择。

自动识别默认关闭。开启后填写开始/结束功率阈值（结束阈值低于开始阈值）和正数确认时长，建议开始 30 秒、结束 300 秒。开始候选出现时即锁定身份，持续达标后回溯至候选时刻开始。短暂停顿仍是一笔，持续低功率确认结束后回溯终点，并撤销终点后的暂计电量/费用。充电中改变 select 仅影响下一笔；**修改本次身份** 才会整笔转移既有记录，电量和价格保持不变。

手动记录由手动结束。手动结束自动记录时若功率仍高，会等待再次观察到低功率才允许新的自动开始。不可用和停机打断持续条件，不能当成零功率。已确认的活动记录及其锁定身份在重载/重启后恢复。

账本在记录边界、本地午夜和价格变化处切分计量区间。正常短间隔按实际秒数分摊，并标记 **估算**，十进制分段总量守恒。例如 23:59:50–00:00:20 的 0.060 kWh 分别归属两天 0.020/0.040 kWh。活动及等待结束的记录带 **暂计** 标记，回溯结束或修订可能减少统计；展示精度不会舍入账本原值。

时刻以 UTC 保存，每笔记录保留其采用的 HA 记账时区。日历按该时区计算，夏令时日不固定为 24 小时；持续时间按实际经过秒数。修改时区只影响新记录，不重分历史。今日/本月/本年以当前 HA 日历标签确定目标，再按每笔记录原记账时区及已保存日期归属；完成次数按原时区的开始日期计入，活动数统计与周期相交的活动记录。自选 start/end 范围仍按绝对 UTC 时间交集剪裁。已结束记录可能 **待结算**，下一次覆盖终点的有效电量读数会补齐尾段，也可同时按边界分给下一笔，不重复计量。

默认最大自动分摊间隔为 **600 秒**。更长间隔或明确不可用的缺口不会被静默归属给身份、日期和价格。可靠的表底总增量仍可推进原生实体累计，但记录口径保留不完整状态。之后可由保留历史/Recorder 补齐，否则通过预览后的人工修订处理。重复的相同表底上报能刷新观测覆盖，不增加电量。

**记录统计与原生 Utility Meter 统计不同。** 原生周期电表包含待机和未形成记录的用电；补录、编辑、身份转移及回溯结束只修改账本，不回写 Utility Meter。下一读数可能补齐账本上一天的尾段，但不重写原生电表已关闭的周期。身份周期实体可以增减，不是 `total_increasing`；Recorder 的旧状态图不代表重算后的账本历史。卡片图表直接查询修订后的账本分桶。

## 补录与修订

在卡片选择 **补录**，或打开已结束记录 → **编辑记录**，填写充电点、身份、记账本地起止时间、可选人工电量、费用依据和备注，再 **预览修改 → 保存预览**。编辑保留原记录时区；夏令时重复时间要求选择 UTC 时刻，不存在的当地时间会被拒绝。

优先采用自有保留观测，不足时通过 HA Recorder 历史接口读取。仅功率点使用原生 Integral 的电量历史；不会自行积分该辅助元素创建之前的原始功率。人工电量替换本次计量依据，不与历史值重复相加。人工补录跨午夜 3 小时 21 kWh，若两天分别占 1/2 小时，则分配 7/14 kWh。

费用依据可选可用历史/电价、人工总费用、待补充（`null`）；编辑还可保留原费用依据。人工总量按时间分摊，并标记人工/估算。编辑时清空人工电量是保留原依据，不提供通过清空来移除既有人工覆盖的操作。未知或部分未知费用始终明确标记不完整。

同点有效记录禁止重叠；相邻记录允许共用边界，不同点允许同时充电。活动起止边界通过开始/结束控制，不可任意历史编辑。作废保留修订轨迹，但退出统计。保存会再次验证重叠、配置及版本，过期/冲突预览需要刷新，不覆盖别人刚完成的修改。重复提交复用相同请求 ID 和原字段。记录列表按点/身份分页，**统计日期范围不筛选“记录 · 全部日期”列表**。

## 原生动作与可复制 YAML

原生动作工具提供 `charge_tally.start`、`charge_tally.end`、`charge_tally.reassign`。可以选择可选的充电点身份 select 实体，也可填写 `point_id`；结束和身份转移还可只填写 `record_id`。同时填写的定位信息必须属于同一点。旧自动化的 `target.entity_id` 继续兼容。多实体、设备/区域、外部 select 或无权记录会被拒绝；记录权限以调用者对本点身份 select 的权限为锚点，配置管理仅管理员可用。

将下面的实体 ID 换成你的实际 ID。开始动作默认使用该点已选择的身份：

```yaml
action: charge_tally.start
data:
  entity_id: select.garage_identity
  request_id: "{{ now().isoformat() }}"
```

自动化结束时，从该点 **Status** 状态实体读取当前记录 ID 与版本。当前记录电量/费用实体也提供这些小属性，结束后清空。电量更新可能提升版本，不要写死为 1：

```yaml
actions:
  - variables:
      record_id: "{{ state_attr('sensor.garage_status', 'record_id') }}"
      record_revision: "{{ state_attr('sensor.garage_status', 'record_revision') }}"
      operation_id: "{{ now().isoformat() }}"
  - condition: template
    value_template: "{{ record_id is not none and record_revision is not none }}"
  - action: charge_tally.end
    data:
      record_id: "{{ record_id }}"
      expected_revision: "{{ record_revision }}"
      request_id: "{{ operation_id }}"
```

历史记录身份转移示例：把所有示例值换成所选记录的实际信息：

```yaml
action: charge_tally.reassign
data:
  record_id: REPLACE_WITH_RECORD_ID
  identity_id: REPLACE_WITH_IDENTITY_ID
  expected_revision: 7  # Replace with the current revision.
  request_id: REPLACE_WITH_UNIQUE_OPERATION_ID
```

卡片支持按身份名称操作；经过认证的 WS `charge_tally/snapshot` 返回点/身份稳定 ID 和当前 `identity_entity_id`，`charge_tally/records` 携带 `record_id` 可查询详情/修订。动作响应可选，返回记录对象。同一逻辑操作重试必须保留原 **request_id 和所有字段**，不能再次生成时间戳；自动化稍后重试时应持久保留这些值。新的逻辑操作使用新 ID。开始/结束采用服务器当前时间，过去时段使用预览/提交。版本冲突后重新读取当前记录，再明确发起新操作。

## 看板卡片

Lovelace **storage 资源模式**下，集成自动幂等注册一个本地 JavaScript 模块；**YAML 资源模式**请加入已有资源配置：

```yaml
lovelace:
  resources:
    - url: /charge_tally/charge-tally-card.js?v=0.1.0
      type: module
```

刷新浏览器，在卡片选择器添加 **Charge Tally**，通过可视化编辑器选择点、身份和显示区块。集成不会自动修改你的看板布局。等价卡片 YAML：

```yaml
type: custom:charge-tally-card
title: 充电记录
show_records: true
show_chart: true
# point_id: REPLACE_WITH_POINT_ID
# identity_id: REPLACE_WITH_IDENTITY_ID
```

卡片支持中英文和 HA 主题。升级后刷新资源缓存，断线恢复或集成重载会获取新的授权快照。没有显示充电点时，检查集成运行状态和本点身份 select 的权限。缺失 Integral/Utility Meter 应通过点的 HA 修复提示修复，不要重建账本。

## 数据、备份与升级

数据库位于 `<config>/charge_tally/ledger.sqlite3`。记录、计费分段与修订长期保存，直到用户明确清理；首版没有自动删记录或批量清理界面。无引用的观测/价格默认保留 90 天，被保留记录、活动工作或未处理缺口引用的数据受保护。更旧的未记账历史依赖 Recorder 保留数据或人工输入。删除充电点、卸载集成都不静默删除账本。运行时不要手工编辑 SQLite 或 HA `.storage`。

备份应覆盖 **完整 HA 配置**，包括 `charge_tally/`、配置条目、实体注册表和 `.storage/charge_tally.<entry_id>.helpers` 所有权映射。仅账本无法重建充电点配置和原生辅助元素。备份 hooks 暂停写入，通过 SQLite 一致性备份 API 生成 `charge_tally/ledger.backup.sqlite3`，备份结束后继续处理排队事件。旧快照不能替代最新账本。手工复制/恢复文件应先停止 HA，再恢复相互一致的配置和账本。

升级前保存可恢复的完整配置备份及对应旧版代码。用新包替换整个集成代码目录，保留 `<config>/charge_tally/`，重启后核对辅助元素状态、活动记录和总量；不要把发布文件复制到 `.storage`。0.1.0 使用初始 schema 1，没有已发布旧 schema 可做迁移验收。未知 schema 会拒绝加载。不要用旧代码打开新结构账本，回滚应同时恢复匹配的代码、配置和数据库备份。

## 测试与安装包

在 Linux Python 3.14.7、Node 24.19.0 环境执行：

```sh
python -m pip install -r requirements-test-ha.txt
python -m pytest tests/ha -q
python -m unittest discover -s tests/core -v
node --test tests/frontend/*.test.mjs
python scripts/package.py
```

CI 固定 HA 2026.9.1、pytest 插件 0.13.364、pytest 9.0.3。打包脚本校验 manifest/项目/前端版本、本地模块路径和严格文件白名单，固定 ZIP 时间与权限并输出 SHA-256。包内只有 `custom_components/charge_tally/` 的代码、本地 JS 与必要资源，不含测试、账本、密钥或本地设计资料。在相同 Python/zlib 环境重复构建字节一致，构建产物由 Git 忽略。

自动验收使用真实 HA 配置流程、Integral/Utility Meter、事件、认证 WS 和 SQLite，覆盖历史预览/提交、整笔身份转移、卸载/重载；独立测试还覆盖权限、负价/未知价格、夏令时、缺口、重叠、版本冲突、订阅及辅助元素所有权。已验证 **应用进程在提交前突然退出** 的事务一致性、随后正常提交、备份 hooks 和 SQLite 快照恢复；这不等于操作系统掉电测试或完整 HA BackupManager 压缩包恢复认证。

手工浏览器验收使用独立官方 HA 2026.9.1 实例和模拟实体，验证配置、自动/手动记录、身份锁定/转移、原生电表口径差额和本地卡片创建/历史预览。没有使用真实充电设备、电表或现有用户 HA 部署；其他 HA 版本和供应商特有实体行为不在本次基线范围内。

许可证：[MIT](LICENSE)。

### 日历查询与预发布账本币种恢复

WebSocket `charge_tally/query` 支持二选一：`calendar_period: daily|monthly|yearly`，或同时提供带时区的 `start` 和 `end`。两种模式互斥，均支持 `point_id` 和 `identity_id` 筛选。卡片默认周期与身份实体使用日历模式；修改 HA 时区后，自选绝对范围与日历模式可能有意产生不同结果。

已有数据但尚未绑定币种的预发布账本：先停止 Charge Tally 写入并创建 SQLite 一致性备份，核对原配置币种后，对保留数据库调用 `Ledger.bind_currency(原币种, confirm_existing=True)`。该操作仅绑定元数据，不转换金额、不更改记录、价格版本或修订。普通新安装和同币种恢复不需要人工改库；此 API 不能替换已经绑定的币种。
