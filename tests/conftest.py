"""pytest 公共配置。

tools/ 下的脚本刻意不是包（仓库既有 10 个工具全部零交叉导入、脚本式运行），
所以测试用 sys.path 显式把 tools/ 加进来导入它们，而不是把它们改成包。
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
