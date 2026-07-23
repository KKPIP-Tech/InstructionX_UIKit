"""layouts 包级再导出：12 个布局预设 + 共享辅助件。

所有布局均为 **API 驱动**：内容由调用方传入（``items`` / ``cards`` /
``sections`` 等参数或 ``set_items`` / ``set_content`` 方法），不传内容
时显示优雅的空占位（「在此放置内容」），包内无任何假数据。
"""

from .card_grid import CardGrid, create_card_grid
from .centered_container import CenteredContainer, create_centered_container
from .dashboard_grid import DashboardGrid, create_dashboard_grid
from .helpers import (
    TokenColorChip,
    apply_token_font,
    empty_placeholder,
    titled_card,
)
from .hero_section import HeroIllustration, HeroSection, create_hero_section
from .holy_grail import HolyGrail, create_holy_grail
from .master_detail import MasterDetail, create_master_detail
from .media_left_right import MediaLeftRight, MediaSection, create_media_left_right
from .sidebar_layout import SidebarLayout, create_sidebar_layout
from .single_column import SingleColumn, create_single_column
from .split_panel import SplitPanel, create_split_panel
from .top_nav_bar import TopNavBar, create_top_nav_bar
from .waterfall import Waterfall, create_waterfall

__all__ = [
    "CardGrid", "create_card_grid",
    "CenteredContainer", "create_centered_container",
    "DashboardGrid", "create_dashboard_grid",
    "HeroSection", "HeroIllustration", "create_hero_section",
    "HolyGrail", "create_holy_grail",
    "MasterDetail", "create_master_detail",
    "MediaLeftRight", "MediaSection", "create_media_left_right",
    "SidebarLayout", "create_sidebar_layout",
    "SingleColumn", "create_single_column",
    "SplitPanel", "create_split_panel",
    "TopNavBar", "create_top_nav_bar",
    "Waterfall", "create_waterfall",
    # helpers
    "TokenColorChip", "apply_token_font", "empty_placeholder", "titled_card",
]
