from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


PartID = str
PartInstanceID = str
PinID = str
NodeID = str


@dataclass
class PartPin:
    pin_id: PinID  # This may not be globally unique, must be unique per part
    short_name: str  # This will not have the word "pin" in it and should have all space trimmed
    description: Optional[str]


@dataclass(kw_only=True)
class Part:
    part_id: PartID
    short_name: str
    description: Optional[str]
    designator_prefix: str
    # TODO properties: Dict[str, str] # Relevant key-value properties like resistance, capacitance, package, etc...
    pins: Dict[PinID, PartPin]

    def should_show_in_bom(self) -> bool:
        return self != GROUND_PART

    def pin_reference(self, pin_id: PinID) -> str:
        if self == GROUND_PART:
            return '' # Don't need a pin name for ground

        kind = 'lead' if len(self.pins) <= 3 else 'pin'

        short_name = self.pins[pin_id].short_name
        if short_name.isnumeric():
            return f"{kind} {short_name}"  # e.g. "lead 0", "pin 0"
        else:
            return f"{short_name} {kind}"  # e.g. "+ lead", "SCK / PB0 pin"p.short_name 

    def should_show_part_details(self):
        return self.description is not None or self.should_show_pin_descriptions()

    def should_show_pin_descriptions(self):
        # Don't show a table for just a couple of pins
        if len(self.pins) < 3:
            return False

        # Don't show the table if all pins' names are the same as the pin descriptions
        if all((p.description is None or p.short_name.lower() == p.description.lower() for p in self.pins.values())):
            return False

        # Don't show the table if all pin descriptions are the same
        first_pin = next(iter(self.pins.values()))
        if all((first_pin.description == p.description for p in self.pins.values())):
            return False

        return True


@dataclass
class PartInstance:
    """ Represents an instance of a part """
    part_instance_id: PartInstanceID
    designator: str  # e.g. C1
    part: Part
    # TODO instance specific label when relevant

    def __lt__(self, other):
        return self.part_instance_id < other.part_instance_id


@dataclass(frozen=True)
class Connection:
    part_instance: PartInstance
    pin_id: PinID


@dataclass
class Node:
    node_id: NodeID
    label: Optional[str]
    connections: List[Connection]


@dataclass
class Schematic:
    part_instances_by_id: Dict[PartInstanceID, PartInstance] = field(default_factory=dict)
    nodes_by_id: Dict[NodeID, Node] = field(default_factory=dict)

GROUND_PART = Part(
    part_id='GROUND',
    short_name='Ground',
    description=None,
    designator_prefix='',
    pins={'common': PartPin('common', 'common', None)}
)

GROUND_PART_INSTANCE = PartInstance(
    part_instance_id= 'net:GROUND',
    designator= 'GND',
    part=GROUND_PART,
)
