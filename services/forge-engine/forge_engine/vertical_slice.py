from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any


# Actual component imagery. The API serves these through a local cache/proxy so the
# Electron renderer never depends on third-party hotlink behavior.
RASPBERRY_PI_IMAGES = [
    "https://commons.wikimedia.org/wiki/Special:Redirect/file/Raspberry%20Pi%204%20B.png?width=640",
]
SOLENOID_IMAGES = [
    "https://cdn.webshopapp.com/shops/304271/files/447773099/solenoid-push-pull-12v-5n.jpg",
    "https://commons.wikimedia.org/wiki/Special:Redirect/file/Solenoide%20Push-Pull.png?width=640",
]
RELAY_IMAGES = [
    "https://commons.wikimedia.org/wiki/Special:Redirect/file/SRD-05VDC-SL-C%205V%20one-channel%20relay%20module.jpg?width=640",
]


class VerticalSliceProject:
    """Canonical state for the first ForgeCAD v2 vertical slice."""

    def __init__(self) -> None:
        self.name = "Adaptive Latch Assembly"
        self.revision = 1
        self.active_branch = "baseline"
        self.branches: list[dict[str, Any]] = [
            {"name": "baseline", "head_commit": "b7e1c4a", "parent_branch": None, "status": "working", "physical_verified": True, "protected": True, "commit_count": 5},
            {"name": "solenoid-swap", "head_commit": "39a18ef", "parent_branch": "baseline", "status": "not_working", "physical_verified": False, "protected": False, "commit_count": 2},
            {"name": "pi-control-v2", "head_commit": "a8c23d1", "parent_branch": "baseline", "status": "unverified", "physical_verified": False, "protected": False, "commit_count": 1},
        ]
        self.parts = [
            {"id": "mounting-bracket", "name": "Mounting base + bracket", "role": "structure", "mass_g": 182, "material": "6061-T6 aluminum", "programmable_workspace_id": None},
            {"id": "latch-body", "name": "Latch body", "role": "mechanism", "mass_g": 126, "material": "6061-T6 aluminum", "programmable_workspace_id": None},
            {"id": "solenoid", "name": "JF-0530B Push-Pull Solenoid", "role": "actuator", "mass_g": 105, "material": "steel / copper", "programmable_workspace_id": None},
            {"id": "raspberry-pi", "name": "Raspberry Pi 4 Model B", "role": "controller / edge compute", "mass_g": 46, "material": "PCB assembly", "programmable_workspace_id": "pi-main"},
            {"id": "battery", "name": "LiPo 11.1V 2200mAh", "role": "power", "mass_g": 174, "material": "LiPo", "programmable_workspace_id": None},
        ]
        self.components = [
            {
                "id": "jf-0530b-12v", "manufacturer": "Generic / JF", "model": "JF-0530B", "category": "solenoid",
                "image": {"kind": "supplier", "source": "Supplier listing / Wikimedia fallback", "sources": SOLENOID_IMAGES},
                "key_specs": [{"label": "Voltage", "value": "12 V DC"}, {"label": "Force", "value": "5 N"}, {"label": "Stroke", "value": "10 mm"}],
                "price": {"amount": 8.90, "currency": "USD", "supplier": "Supplier listing"}, "fit_score": 95,
                "fit_reason": "Fits the latch envelope and 12 V rail; verify continuous-duty heating.", "unknown_required_fields": ["continuous_duty_cycle"], "geometry_fidelity": "proxy",
            },
            {
                "id": "srd-05vdc", "manufacturer": "Songle", "model": "SRD-05VDC-SL-C", "category": "relay",
                "image": {"kind": "reference", "source": "Wikimedia Commons", "sources": RELAY_IMAGES},
                "key_specs": [{"label": "Coil", "value": "5 V DC"}, {"label": "Contacts", "value": "10 A / 250 VAC"}, {"label": "Type", "value": "SPDT"}],
                "price": {"amount": 0.99, "currency": "USD", "supplier": "Mouser"}, "fit_score": 87,
                "fit_reason": "Useful as an isolated switching option; MOSFET remains preferable for PWM.", "unknown_required_fields": [], "geometry_fidelity": "proxy",
            },
            {
                "id": "raspberry-pi-4b", "manufacturer": "Raspberry Pi", "model": "Raspberry Pi 4 Model B", "category": "compute",
                "image": {"kind": "reference", "source": "Wikimedia Commons", "sources": RASPBERRY_PI_IMAGES},
                "key_specs": [{"label": "CPU", "value": "Quad-core 1.5 GHz"}, {"label": "RAM", "value": "4 GB"}, {"label": "Power", "value": "5 V USB-C"}],
                "price": {"amount": 55.00, "currency": "USD", "supplier": "Raspberry Pi"}, "fit_score": 92,
                "fit_reason": "Already present in the baseline assembly and exposes the attached code workspace.", "unknown_required_fields": [], "geometry_fidelity": "manufacturer_mesh", "added": True,
            },
        ]
        self.workspaces: dict[str, dict[str, Any]] = {
            "pi-main": {
                "id": "pi-main", "device_part_id": "raspberry-pi", "target": "Raspberry Pi 4 Model B", "runtime": "Python 3",
                "files": {
                    "src/main.py": "import RPi.GPIO as GPIO\nimport time\n\nSOLENOID_PIN = 17\nLIMIT_SWITCH_PIN = 27\n\nGPIO.setmode(GPIO.BCM)\nGPIO.setup(SOLENOID_PIN, GPIO.OUT, initial=GPIO.LOW)\nGPIO.setup(LIMIT_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)\n\ndef is_latch_closed():\n    return GPIO.input(LIMIT_SWITCH_PIN) == GPIO.LOW\n",
                    "src/latch_control.py": "def command_latch(closed: bool) -> None:\n    # Hardware implementation lives here.\n    pass\n",
                    "src/motor_driver.py": "# Reserved for alternate actuator experiments.\n",
                    "src/sensors.py": "# Limit switch / current sensing helpers.\n",
                    "config/config.json": "{\n  \"solenoid_pin\": 17,\n  \"limit_switch_pin\": 27\n}\n",
                    "README.md": "# Adaptive Latch controller\n\nVersioned with the ForgeCAD design branch.\n",
                },
            }
        }
        self.history = [
            {"time": self._now(), "actor": "human", "message": "Marked baseline as working in real life", "branch": "baseline"},
            {"time": self._now(), "actor": "forge", "message": "Created solenoid-swap experiment", "branch": "solenoid-swap"},
        ]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "revision": str(self.revision),
            "active_branch": self.active_branch,
            "branches": [{**deepcopy(b), "active": b["name"] == self.active_branch} for b in self.branches],
            "parts": deepcopy(self.parts),
            "history": deepcopy(self.history[-30:]),
            "selected_part_id": "raspberry-pi",
        }

    def scene_manifest(self) -> dict[str, Any]:
        # These transforms describe a physically coherent assembled state. The renderer
        # currently uses matching procedural geometry and will later consume this manifest directly.
        positions = {
            "mounting-bracket": [0.0, -1.35, 0.0],
            "latch-body": [2.25, -0.34, 0.0],
            "solenoid": [0.25, -0.70, 0.0],
            "raspberry-pi": [-2.25, -1.02, -0.72],
            "battery": [-2.35, -0.55, 1.02],
        }
        explode_vectors = {
            "mounting-bracket": [0.0, 0.0, 0.0],
            "latch-body": [1.0, 0.28, 0.0],
            "solenoid": [-0.55, 0.38, 0.0],
            "raspberry-pi": [-0.75, 0.16, -0.75],
            "battery": [-0.8, 0.25, 0.72],
        }
        return {
            "revision": str(self.revision), "branch": self.active_branch, "assets": [],
            "parts": [
                {"id": p["id"], "name": p["name"], "semantic_role": p["role"], "asset_id": f"procedural:{p['id']}", "geometry_fidelity": "proxy",
                 "transform": {"position": positions[p["id"]], "quaternion": [0, 0, 0, 1], "scale": [1, 1, 1]},
                 "explode_vector": explode_vectors[p["id"]], "explode_group": p["role"],
                 "programmable_workspace_id": p["programmable_workspace_id"]}
                for p in self.parts
            ],
        }

    def search_components(self, query: str = "") -> list[dict[str, Any]]:
        q = query.strip().lower()
        items = self.components if not q else [c for c in self.components if q in f"{c['manufacturer']} {c['model']} {c['category']}".lower()]
        return deepcopy(items)

    def component(self, component_id: str) -> dict[str, Any]:
        return deepcopy(next(c for c in self.components if c["id"] == component_id))

    def add_component(self, component_id: str) -> dict[str, Any]:
        component = next(c for c in self.components if c["id"] == component_id)
        if not component.get("added"):
            component["added"] = True
            self.revision += 1
            self.history.append({"time": self._now(), "actor": "human", "message": f"Added component {component['model']}", "branch": self.active_branch})
        return deepcopy(component)

    def activate_branch(self, branch_name: str) -> dict[str, Any]:
        if branch_name not in {b["name"] for b in self.branches}:
            raise KeyError(branch_name)
        if branch_name != self.active_branch:
            self.active_branch = branch_name
            self.history.append({"time": self._now(), "actor": "human", "message": f"Switched to {branch_name}", "branch": branch_name})
        return self.snapshot()

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.workspaces[workspace_id]
        return {k: deepcopy(v) for k, v in workspace.items() if k != "files"} | {"files": sorted(workspace["files"].keys())}

    def read_file(self, workspace_id: str, file_path: str) -> dict[str, str]:
        path = str(PurePosixPath(file_path))
        return {"path": path, "content": self.workspaces[workspace_id]["files"][path]}

    def write_file(self, workspace_id: str, file_path: str, content: str) -> dict[str, str]:
        path = str(PurePosixPath(file_path))
        if path.startswith("../") or path.startswith("/"):
            raise ValueError("Workspace path escapes the device workspace")
        self.workspaces[workspace_id]["files"][path] = content
        self.revision += 1
        self.history.append({"time": self._now(), "actor": "human", "message": f"Edited {path}", "branch": self.active_branch})
        return {"path": path, "content": content}

    def apply_agent_change(self, text: str) -> dict[str, Any]:
        source_branch = next(b for b in self.branches if b["name"] == self.active_branch)
        stem = "solenoid-swap" if "solenoid" in text.lower() else "ai-variant"
        existing = {b["name"] for b in self.branches}
        name = stem
        i = 2
        while name in existing:
            name = f"{stem}-{i}"
            i += 1
        branch = {
            "name": name, "head_commit": f"v2{self.revision:05x}", "parent_branch": source_branch["name"], "status": "unverified",
            "physical_verified": False, "protected": False, "commit_count": 1,
        }
        self.branches.append(branch)
        self.active_branch = name
        self.revision += 1
        if "12v" in text.lower() and "solenoid" in text.lower():
            solenoid = next(p for p in self.parts if p["id"] == "solenoid")
            solenoid["name"] = "JF-0530B Push-Pull Solenoid (12V)"
        self.history.append({"time": self._now(), "actor": "forge-agent", "message": text[:180], "branch": name})
        return {"branch": name, "revision": str(self.revision), "project": self.snapshot()}


PROJECT = VerticalSliceProject()
