# 光伏电站限电事件与损失电量复算

给新能源场站运营分析员使用。仅用有效对照逆变器和相同辐照区间拟合基线；重叠限电事件先求并集再积分。

七个业务模块：遥测采信、设备映射、事件切片、基线拟合、损失核算、能量对账、运行归档。

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

访问 http://localhost:18244 。启动直接载入现场脏批。切换干净样例、旧编码样例和响应确认批可对照核验。完整对照批INV-A重叠事件取并集后30分钟，基线100kW、实际60kW，损失20kWh；无合格对照或遥测冲突必须保持未定，不能填0。

调度指令只划定限电时段，可结算以现场遥测的响应与恢复证据为准（响应确认批 `response` 同屏演示三类裁定）：INV-A 下挫达标且事件结束后600秒窗口内的10:40样本回到基线5%容差，3段全额可结算20kWh；INV-B 出力仅下挫4%未达10%门槛，裁定待查响应（PENDING_RESPONSE）不混入正式损失；INV-C 已下挫但恢复窗口内无恢复遥测，裁定待查恢复（PENDING_RECOVERY）。缺测、故障或无对照片段保持未定（UNCONFIRMED，null损失不填0）。损失页与对账页分列“可结算时段”和“待查响应时段”，可结算+待查等于全部已确定损失（结算守恒），存在待查或未定时封存保持待复核。门槛与容差可经 `overrides` 的 `response_drop_ratio`、`recovery_tolerance`、`recovery_window_seconds` 复核。

复核重算 `POST /api/runs/{run_id}/rerun` 先基于不可变输入快照完整重算，再在单事务内按同批号原子替换：重算失败（含业务错误与运行时异常）时尚未写库，旧版结果、revision 与“已复核”状态原样保留；失败后重试不新增批次、不丢数据，复核版本号不被清零。

各模块页面对应 `/<模块英文名>`，各模块执行入口为 `POST /api/<模块英文名>`，不传参即可独立演示。完整运行 `POST /api/runs` 支持 `dataset`（dirty/clean/legacy/response）、`csv_text` 与 `overrides` 参数。批次历史 `GET /api/runs`，详情 `GET /api/runs/{run_id}`。

同输入与规则版本生成相同批号，只保留一条批次。复核入口 `POST /api/runs/{run_id}/review` 提交当前 `revision`，陈旧提交409。归档包只有一个下载入口 `GET /api/export/{run_id}`，含证据和运行摘要。原始隔离在页面同屏显示。

SQLite使用命名卷，容器重启后保留历史。要重建演示可在Compose中改用新的卷名称，保留旧卷。

源码在 `app/`，样例在 `sample_data/`，测试在 `tests/`；定义见 `docs/DATA-DICTIONARY.md`，模块和边界测试对应关系见 `docs/DEPTH.md`。输入上限2MB，属于离线复核工具。

采信页支持上传或粘贴CSV。完整源字节与参数随批次持久化，跨页通过run_id读取同一结果。`POST /api/runs/{run_id}/rerun` 读取该批不可变输入快照重新计算，规则未变时批号不变。切换另一示例则创建或复用另一批次。
