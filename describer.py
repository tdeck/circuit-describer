from collections import defaultdict

import jinja2

from models import *

@dataclass
class PartInfo:
    part: Part
    instances: List[PartInstance]

    def __lt__(self, other):  # TODO do we need this?
        return self.part.part_id < other.part.part_id

def collect_parts(schematic: Schematic) -> List[PartInfo]:
    """
    Returns ordered list of PartInfo values.
    """

    instances_by_part_id: Dict[PartId, PartInstance] = defaultdict(list)
    for pinst in schematic.part_instances_by_id.values():
        instances_by_part_id[pinst.part.part_id].append(pinst)

    part_infos: List[PartInfo] = []
    for part_id, instances in instances_by_part_id.items():
        part_infos.append(PartInfo(
            part=instances[0].part,
            instances=sorted(instances),
        ))

    return part_infos


@jinja2.pass_eval_context
def nl2br(eval_ctx, value):
    return value.replace("\n", "<br>\n")


def describe_as_html(schematic: Schematic) -> str:
    jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader("."))
    jinja_env.filters["nl2br"] = nl2br

    template = jinja_env.get_template("template.html.jinja2")
    return template.render(schematic=schematic, parts=collect_parts(schematic))
