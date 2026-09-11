"""Auditable lighting quantity estimate; independent of the ten-node simulator.

Map: assets/campus_map.png. Buildings identify scope, not measured floor areas.
All dimensions/densities are editable design assumptions. A node controls one
room/lighting section, or one outdoor pole; fixture counts are separate.
"""
from math import ceil


def building_item(item_id, area_id, name, buildings, floors, sections, fixtures, basis):
    return dict(item_id=item_id, area_id=area_id, name=name, kind="building",
                buildings=buildings, floors=floors, sections_per_floor=sections,
                fixtures_per_node=fixtures, basis=basis)


def road_item(item_id, area_id, name, routes, length_m, spacing_m=25, closed=False):
    return dict(item_id=item_id, area_id=area_id, name=name, kind="road",
                routes=routes, length_m=length_m, spacing_m=spacing_m, closed=closed,
                fixtures_per_node=1,
                basis="分区分配的道路长度与25m间距均为设计假设，非地图量测或照明规范结论；每杆1灯1节点")


LIGHTING_PLAN = [
    building_item("MAIN-ROOM", "PA01", "主楼教室", 1, 10, 10, 12,
                  "用户给定10层×每层10间教室；每教室12灯、1控制节点为已确认估算口径"),
    building_item("MAIN-CORRIDOR", "PA01", "主楼公共走廊", 1, 10, 4, 3, "每层4个独立控制段，每段3灯；不含楼梯"),
    building_item("MAIN-STAIR", "PA01", "主楼楼梯间", 1, 10, 2, 2, "每层2处楼梯照明区，每区2灯"),
    building_item("MAIN-ENTRY", "PA01", "主楼出入口", 1, 1, 2, 2, "2处出入口，每处2灯"),
    road_item("MAIN-ROAD", "PA01", "主楼专属环路", 1, 400, closed=True),
    building_item("TEACH-ROOM", "PA02", "教一至教四教室", 4, 6, 8, 12, "地图确认4栋；每栋6层、每层8间教室均为估算"),
    building_item("TEACH-CORRIDOR", "PA02", "教学楼公共走廊", 4, 6, 4, 3, "每层4段，每段3灯"),
    building_item("TEACH-STAIR", "PA02", "教学楼楼梯间", 4, 6, 2, 2, "每层2处楼梯照明区，每区2灯"),
    building_item("TEACH-ENTRY", "PA02", "教学楼出入口", 4, 1, 2, 2, "每栋2处，每处2灯；外部道路统一归PA07"),
    building_item("LIB-READ", "PA03", "图书馆阅览及书库分区", 1, 6, 8, 12, "6层×每层8个照明分区，每区12灯；分区不是独立房间实测数"),
    building_item("LIB-COMMON", "PA03", "图书馆走廊与楼梯", 1, 6, 6, 2, "每层公共空间合计6个控制区，每区2灯"),
    building_item("ACTIVITY", "PA03", "学生活动中心", 1, 3, 6, 8, "3层×每层6个照明区，每区8灯"),
    building_item("CANTEEN", "PA03", "学生食堂公共区", 1, 2, 8, 10, "地图学生食堂按2层、每层8区估算；归PA03且不在PA05重复计数"),
    road_item("LIB-PATH", "PA03", "图书馆及活动中心专属步道", 1, 300),
    building_item("SPORT-FIELD", "PA04", "体育场高杆灯", 1, 1, 8, 4, "8杆，每杆4盏泛光灯、1节点；非照度设计结论"),
    building_item("SPORT-GYM", "PA04", "体育馆分区", 1, 1, 4, 12, "4个照明控制区，每区12灯"),
    building_item("SPORT-POOL", "PA04", "游泳馆分区", 1, 1, 4, 8, "4个照明控制区，每区8灯"),
    building_item("SPORT-BASKET", "PA04", "篮球场灯杆", 4, 1, 4, 2, "地图球场区域按4片场地估算，每片4杆、每杆2灯"),
    building_item("SPORT-TENNIS", "PA04", "网球排球活动区灯杆", 2, 1, 4, 2, "按2片场地估算，每片4杆、每杆2灯"),
    road_item("SPORT-PATH", "PA04", "体育场馆及健身步道", 1, 400),
    building_item("DORM-CORRIDOR", "PA05", "公寓公共走廊", 13, 6, 4, 3, "地图公寓建筑群按13栋公共照明单元估算（含留学生等公寓）；每栋6层，不含宿舍房间"),
    building_item("DORM-STAIR", "PA05", "公寓楼梯间", 13, 6, 2, 2, "与走廊相同13栋、6层，每层2区、每区2灯"),
    building_item("DORM-ENTRY", "PA05", "公寓出入口", 13, 1, 2, 2, "每栋2处，每处2灯；不重复计算食堂"),
    building_item("SERVICE", "PA05", "学生综合服务及商业公共区", 2, 2, 4, 6, "合并为2个公共服务建筑单元，每单元2层、每层4区、每区6灯"),
    road_item("DORM-PATH", "PA05", "公寓组团内部步道", 1, 600),
    building_item("RESEARCH-ROOM", "PA06", "科研楼与协同创新中心公共工作区", 2, 8, 8, 8, "地图2栋按各8层、每层8个公共工作照明区估算，每区8灯"),
    building_item("RESEARCH-CORRIDOR", "PA06", "科研楼走廊", 2, 8, 4, 3, "每层4段，每段3灯"),
    building_item("RESEARCH-STAIR", "PA06", "科研楼楼梯间", 2, 8, 2, 2, "每层2区，每区2灯"),
    building_item("HALL", "PA06", "科学会堂", 1, 3, 6, 8, "按3层、每层6个公共照明区估算，每区8灯"),
    building_item("RESEARCH-ENTRY", "PA06", "科研及会堂出入口", 3, 1, 2, 2, "3栋各2处，每处2灯；楼外道路归PA07"),
    road_item("ROAD-NS", "PA07", "校园南北向公共干路", 2, 650),
    road_item("ROAD-EW", "PA07", "校园东西向公共干路", 3, 400),
    building_item("GATE", "PA07", "四个校门照明", 4, 1, 4, 1, "东、西、南、北门各4盏；不含道路路灯"),
    building_item("PARKING", "PA07", "停车与公共广场", 4, 1, 6, 1, "按4处公共空间、每处6杆估算；不含体育场专属照明"),
    road_item("PUBLIC-ROAD", "PA08", "家属区及公共服务专属道路", 1, 500),
    building_item("HOSPITAL", "PA08", "校医院公共走廊与楼梯", 1, 4, 4, 3, "4层、每层4个公共区、每区3灯；不含诊室专用照明"),
    building_item("KINDER", "PA08", "幼儿园公共活动区", 1, 3, 3, 6, "3层、每层3区、每区6灯；无个人数据采集"),
    building_item("PUBLIC-ENTRY", "PA08", "医院幼儿园及家属区公共入口", 3, 1, 2, 2, "3组公共入口各2区、每区2灯；不含住户室内照明"),
]

PLAN_BOUNDARY = (
    "本次为地图分区下的照明数量估算，主楼层数与教室数采用用户输入；其他楼层、分区、灯数、道路长度均待勘测。"
    "独立控制节点按教室/分区/灯杆计，灯具按实际灯头计。"
    "道路清单按互不重叠的管理路段分配：PA01/03/04/05/08仅计专属环路或内部步道，PA07仅计剩余公共干路、校门和广场；"
    "路口灯位由所属清单唯一计入，不将相邻路段端点理解为同一杆重复计数。"
    "食堂统一归PA03；公寓不含寝室、家属区不含住户室内、医院不含诊室专用灯。"
    "未估算应急疏散专用回路；施工前需单独核定。"
    "三网关仅是现有仿真拓扑，数量扩大不代表已通过通信容量或覆盖验收。"
)


def calculate_item(item):
    """Calculate one row with explicit factors (open roads include both ends)."""
    if item["kind"] not in {"building", "road"}:
        raise ValueError(f"未知清单类型：{item['kind']}")
    keys = ("buildings", "floors", "sections_per_floor", "fixtures_per_node") if item["kind"] == "building" else ("routes", "length_m", "spacing_m", "fixtures_per_node")
    for key in keys:
        value = item[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{item['item_id']}: {key} 必须为正整数")
    if item["kind"] == "building":
        nodes = item["buildings"] * item["floors"] * item["sections_per_floor"]
        formula = f"{item['buildings']} × {item['floors']} × {item['sections_per_floor']}"
    elif item["kind"] == "road":
        end = 0 if item["closed"] else 1
        nodes = item["routes"] * (ceil(item["length_m"] / item["spacing_m"]) + end)
        formula = f"{item['routes']} × (ceil({item['length_m']}/{item['spacing_m']}) + {end})"
    else:
        raise ValueError(f"未知清单类型：{item['kind']}")
    return {**item, "control_nodes": nodes, "fixtures": nodes * item["fixtures_per_node"],
            "node_formula": formula, "fixture_formula": f"{nodes} × {item['fixtures_per_node']}"}


def estimate_lighting_plan(items=None):
    rows = [calculate_item(item) for item in (LIGHTING_PLAN if items is None else items)]
    if len({r["item_id"] for r in rows}) != len(rows):
        raise ValueError("照明清单 item_id 不得重复")
    areas = {}
    for row in rows:
        total = areas.setdefault(row["area_id"], dict(control_nodes=0, fixtures=0))
        for key in total:
            total[key] += row[key]
    return dict(rows=rows, areas=areas,
                control_nodes=sum(r["control_nodes"] for r in rows),
                fixtures=sum(r["fixtures"] for r in rows))
