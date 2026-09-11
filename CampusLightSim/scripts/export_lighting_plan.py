"""Export the current quantity assumptions and totals for project review."""
from pathlib import Path
import csv
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import CAMPUS_PLANNING_AREAS, DEVICES
from planning import PLAN_BOUNDARY, estimate_lighting_plan


def export_plan():
    plan = estimate_lighting_plan()
    output = ROOT / "docs"
    output.mkdir(exist_ok=True)
    text = [
        "# 校园照明数量估算清单\n",
        "口径修订：2026-09-11。替代原来缺少逐项依据的 69 个建议节点。\n",
        f"**当前规划：{plan['fixtures']:,} 盏灯具，{plan['control_nodes']:,} 个独立控制节点；全部 {len(DEVICES)} 个节点已接入软件仿真。**\n",
        "## 依据与统计口径\n",
        "- 地图来源：项目 assets/campus_map.png；用于确认主楼、教一至教四、图书馆、体育设施、公寓及科研等分区。地图不提供楼层数、室内房间数或精确道路里程。",
        "- 主楼采用用户输入的 10 层×每层 10 间教室。经用户确认，教室暂按 12 盏灯、1 个控制节点；这不是教室照度设计或实测清单。",
        "- 走廊、楼梯按照明分区控制；道路按每杆 1 灯、1 节点；体育场高杆可以 1 节点控制多个灯头。",
        "- 其他建筑数量归组、楼层、公共分区、每区灯数及道路长度均为可调整设计假设，不是地图直接测量结果。",
        "- 公寓按地图建筑群归为 13 个公共照明单元，具体楼栋对应与层数应现场核定；当前不统计寝室内灯具。",
        "- 25 m 路灯间距是本次数量估算参数，不是引用的规范间距；实施须根据道路宽度、配光和照度另行设计。\n",
        PLAN_BOUNDARY + "\n",
        "## 片区汇总\n",
        "| 片区 | 规划控制节点 | 规划灯具 | 已接入节点 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, area in CAMPUS_PLANNING_AREAS.items():
        total = plan["areas"][key]
        text.append(f"| {key} {area['name']} | {total['control_nodes']} | {total['fixtures']} | {area['simulation_nodes']} |")
    text.extend([
        f"| 合计 | {plan['control_nodes']} | {plan['fixtures']} | {len(DEVICES)} |\n",
        "## 主楼核算示例\n",
        "- 教室：10 层×10 间＝100 节点；100×12＝1,200 盏灯。",
        "- 走廊：10 层×4 段＝40 节点；40×3＝120 盏灯。",
        "- 楼梯：10 层×2 区＝20 节点；20×2＝40 盏灯。",
        "- 出入口：2 个节点×2 灯＝4 盏灯。",
        "- 专属环路：估算 400 m，25 m 间距，闭合环路 ceil(400/25)＝16 杆，每杆1灯1节点。",
        "- 主楼片区合计：178 节点、1,380 盏灯；不再用1个教室节点或1个道路节点代表部署总数。\n",
        "## 全部明细\n",
        "建筑数量公式的三个因子依次为建筑单元数、层数、每层控制区；体育场地等单层单元的层数取1。开放道路的端点在专属清单中唯一分配，闭合环路不重复增加端点。\n",
        "| 编号 | 片区 | 对象 | 节点计算式 | 节点 | 灯具计算式 | 灯具 | 假设依据 |",
        "| --- | --- | --- | --- | ---: | --- | ---: | --- |",
    ])
    csv_rows = []
    for row in plan["rows"]:
        text.append(f"| {row['item_id']} | {row['area_id']} | {row['name']} | {row['node_formula']} | {row['control_nodes']} | {row['fixture_formula']} | {row['fixtures']} | {row['basis']} |")
        csv_rows.append({"编号": row["item_id"], "片区": row["area_id"], "对象": row["name"],
                         "节点公式": row["node_formula"], "节点": row["control_nodes"],
                         "灯具公式": row["fixture_formula"], "灯具": row["fixtures"], "假设依据": row["basis"]})
    text.extend([
        "\n## 调整方式与运行边界\n",
        "修改 planning.py 中 LIGHTING_PLAN 的建筑数、楼层、控制区、每节点灯数、道路长度等因子，重启应用后 config.py 自动按片区汇总。运行 `python -B scripts/export_lighting_plan.py` 更新本说明与 CSV。",
        "\n全部规划节点通过 deployment.py 实例化为 DEVICES，每个节点具有独立控制区、环境采样、自动控制记忆、位置与故障状态。主楼每间教室12盏灯×36W=432W，一个节点控制整个回路；公共通道单灯18W，路灯120W，体育高杆单灯200W，其余体育分区100W，其他室内灯36W。功率均为可调整估算。",
        "\n已配置1,690个独立控制区；每天5分钟步长共486,720条采样。实验与测试页新增全量联合仿真入口，可运行5分钟、1小时或24小时，覆盖环境、控制、通信和故障。全量能耗重新积分，不使用旧的17.070/8.349 kWh和51.09%结果。",
        "\n旧版PPT的10个代表节点、69个建议节点及旧能耗是历史快照。当前报告应重新运行计算并更新截图；三网关只用于链路预算模型，不代表已完成1,690节点的LoRaWAN碰撞与容量验证。",
    ])
    (output / "lighting_quantity_plan.md").write_text("\n".join(text), encoding="utf-8")
    with (output / "lighting_quantity_plan.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"Exported {len(csv_rows)} items: {plan['control_nodes']} controllers, {plan['fixtures']} fixtures")


if __name__ == "__main__":
    export_plan()
