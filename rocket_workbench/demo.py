"""A deliberately synthetic demonstration rocket, not certified flight data."""
from .models import Component, FlightConfiguration, Material, Motor, Project


def demo_project() -> Project:
    components = [
        Component(id="nose", name="Ogive nose", kind="nosecone", x=0, length=0.45, radius=0.06, thickness=0.003, mass_override=0.65, material_id="fiberglass", metadata={"nose_shape": "ogive"}),
        Component(id="payload", name="Payload bay — replace with CAD", kind="bodytube", x=0.45, length=0.65, radius=0.06, thickness=0.003, mass_override=1.25, material_id="fiberglass"),
        Component(id="airframe", name="Main airframe", kind="bodytube", x=1.1, length=1.65, radius=0.06, thickness=0.003, mass_override=1.8, material_id="fiberglass"),
        Component(id="fins", name="Fiberglass fins", kind="trapezoidfinset", x=2.3, length=0.4, radius=0.06, thickness=0.005, fin_count=3, root_chord=0.4, tip_chord=0.18, span=0.18, sweep=0.12, material_id="fiberglass"),
        Component(id="avionics", name="Avionics mass", kind="masscomponent", x=1.0, length=0.1, radius=0.035, mass_override=0.4, external=False, material_id="fiberglass"),
    ]
    motor = Motor(id="demo-motor", name="Synthetic demonstration motor", dry_mass=0.75, propellant_mass=0.85, diameter=0.075, length=0.35,
                  curve=[[0, 0], [0.05, 800], [0.15, 1100], [1, 1000], [2, 850], [2.5, 650], [2.8, 0]],
                  source="Synthetic educational curve. Replace with validated manufacturer/test data before design decisions.")
    return Project(name="3 m high-power demonstration", components=components, motors=[motor],
                   materials=[Material(id="fiberglass"), Material(id="aluminum", name="Aluminum 6061-T6", density=2700, youngs_modulus=68.9e9, poisson_ratio=0.33, yield_strength=276e6, description="Typical room-temperature values; verify stock and temper.")],
                   configurations=[FlightConfiguration(id="dual", name="Dual deployment", motor_id=motor.id), FlightConfiguration(id="single", name="Single deployment", motor_id=motor.id, deployment="single")],
                   active_configuration_id="dual", metadata={"demo": True},
                   import_warnings=["Demonstration geometry and motor are synthetic; this is not a validated launch design."])
