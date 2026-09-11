# ForgeCAD real-component layer

ForgeCAD v1 ships an offline deterministic component registry so a design agent can select **real parts**, not just draw anonymous boxes. The built-in catalog currently contains 238 entries across compute, microcontrollers, solenoids, stepper motors, servos, bearings, fasteners, linear motion, fans, batteries, sensors and power electronics.

Each component has a stable ID, category, manufacturer/model identity, envelope dimensions, and relevant engineering attributes such as mass, voltage, torque, force, bore, airflow or load rating when represented. Programmable components also create a code workspace when inserted into a design.

The selector accepts query text plus explicit minimum/maximum constraints. Feasible parts sort before infeasible parts; constraint penalties are returned rather than silently discarded. This makes selection auditable and allows an agent to explain why a physical part was chosen.

The built-in registry is intentionally local/offline. Supplier-specific live catalogs can be layered on later without changing the canonical design or command model.
