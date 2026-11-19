from pathlib import Path
from decimal import Decimal
import json, os
ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / 'app/project.json').read_text())
MODULES = META['keys']
RULE_VERSION = '2026.11.19-r3'
DB_PATH = os.environ.get('DB_PATH', '/data/workbench.sqlite')
SENTINELS = {'', '-', 'N/A', 'NULL', '未知'}
MAX_BYTES = 2_000_000
# 响应确认门槛：指令时段内实际功率低于基线的比例达到该值才认定现场已响应。
RESPONSE_DROP_RATIO = Decimal('0.10')
# 恢复确认容差：事件结束后窗口内实际功率回到基线的该比例以内，认定恢复完成。
RECOVERY_TOLERANCE = Decimal('0.05')
# 恢复确认窗口：事件结束后向前寻找恢复证据的最长秒数，不做无限外推。
RECOVERY_WINDOW_SECONDS = 600
