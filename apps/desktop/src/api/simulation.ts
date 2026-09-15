import { engineFetch } from './engine';

export type SimulationJointType = 'fixed' | 'revolute' | 'prismatic' | 'cylindrical' | 'planar';

export interface SimulationJointEdge {
  joint_id: string;
  name: string;
  type: SimulationJointType;
  parent_id: string;
  child_id: string;
  orientation_source: string;
}

export interface SimulationAssemblyGraph {
  ok: boolean;
  solver: string;
  solver_version: string;
  object_count: number;
  joint_count: number;
  roots: string[];
  edges: SimulationJointEdge[];
  errors: Array<{ code: string; message: string; [key: string]: unknown }>;
  limitations: string[];
}

export interface SimulationHealth {
  ok: boolean;
  version: string;
  release_complete: boolean;
  simulation_schema: number;
  design_fingerprint: string;
  active_branch: string;
  assembly: SimulationAssemblyGraph;
  domains: Record<string, {
    available: boolean;
    grade: string;
    source?: string;
    scope?: string;
    is_cfd?: boolean;
    features?: string[];
  }>;
  external_solvers: Array<Record<string, unknown>> | Record<string, unknown>;
  truth: string;
}

export interface SimulationRun {
  id?: string;
  kind?: string;
  time?: string;
  solver?: string;
  solver_version?: string;
  solver_grade?: string;
  stale?: boolean;
  stale_reason?: string;
  fingerprint_current?: boolean;
  prediction_not_observation?: boolean;
  limitations?: string[];
  result?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SimulationRuns {
  items: SimulationRun[];
  count: number;
  current_count: number;
  design_fingerprint: string;
}

export interface JointPoseInput {
  joint_id: string;
  value?: number;
  rotation_deg?: number;
  translation_mm?: number;
  plane_u_mm?: number;
  plane_v_mm?: number;
  commit?: boolean;
  reason?: string;
}

export interface JointSweepInput {
  joint_id: string;
  start_state: Record<string, number>;
  end_state: Record<string, number>;
  duration_s: number;
  samples?: number;
  gravity_m_s2?: [number, number, number];
  collision_tolerance_mm3?: number;
}

export interface ThermalTransientInput {
  duration_s: number;
  timestep_s: number;
  initial_temperature_c: number;
  max_samples?: number;
}

export interface ThermalFieldInput {
  object_id: string;
  duration_s: number;
  timestep_s: number;
  initial_temperature_c: number;
  heat_w: number;
  convection_h_w_m2k: number;
  ambient_temperature_c: number;
  emissivity?: number;
  grid?: [number, number, number];
  max_samples?: number;
}

export interface AerodynamicInput {
  solver?: 'integral' | 'openfoam';
  object_ids?: string[];
  relative_air_velocity_m_s: [number, number, number];
  air_density_kg_m3: number;
  drag_coefficient: number;
  reference_area_m2?: number;
  lift_coefficient?: number;
  lift_direction?: [number, number, number];
  dynamic_viscosity_pa_s?: number;
  characteristic_length_m?: number;
  center_of_pressure_mm?: [number, number, number];
  moment_reference_mm?: [number, number, number];
}

export interface StructuralInput {
  object_id: string;
  mode?: 'canonical' | 'screening';
  force_n?: number;
  load_direction?: 'x' | 'y' | 'z';
  convergence?: boolean;
}

export interface RigidBodyInput {
  object_ids?: string[];
  force_n?: [number, number, number];
  torque_nm?: [number, number, number];
  gravity_m_s2?: [number, number, number];
  duration_s?: number;
  initial_velocity_m_s?: [number, number, number];
  initial_angular_velocity_rad_s?: [number, number, number];
}

export const fetchSimulationHealth = () => engineFetch<SimulationHealth>('/v6/simulation/health');
export const fetchSimulationGraph = () => engineFetch<SimulationAssemblyGraph>('/v6/simulation/assembly/graph');
export const fetchSimulationRuns = () => engineFetch<SimulationRuns>('/v6/simulation/runs');

export const driveSimulationJoint = (input: JointPoseInput) => engineFetch<Record<string, unknown>>('/v6/simulation/joints/pose', {
  method: 'POST',
  body: JSON.stringify({ ...input, commit: input.commit ?? true }),
});

export async function sweepSimulationJoint(input: JointSweepInput): Promise<Record<string, unknown>> {
  const result = await engineFetch<Record<string, unknown>>('/v6/simulation/joints/sweep', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  const frames = Array.isArray(result.frames) ? result.frames : [];
  if (frames.length && typeof window !== 'undefined') {
    const returnedDuration = Number(result.duration_s);
    window.dispatchEvent(new CustomEvent('forgecad:simulation-preview', {
      detail: {
        frames,
        duration_s: Number.isFinite(returnedDuration) && returnedDuration > 0 ? returnedDuration : input.duration_s,
      },
    }));
  }
  return result;
}

export const runGravityLoadPath = (gravity: [number, number, number] = [0, 0, -9.80665]) => engineFetch<Record<string, unknown>>('/v6/simulation/joints/gravity-loads', {
  method: 'POST',
  body: JSON.stringify({ gravity_m_s2: gravity }),
});

export const runTransientThermal = (input: ThermalTransientInput) => engineFetch<Record<string, unknown>>('/v6/simulation/thermal/transient', {
  method: 'POST',
  body: JSON.stringify(input),
});

export const runThermalField = (input: ThermalFieldInput) => engineFetch<Record<string, unknown>>('/v6/simulation/thermal/field', {
  method: 'POST',
  body: JSON.stringify({ emissivity: 0, grid: [12, 8, 6], max_samples: 120, ...input }),
});

export const runAerodynamics = (input: AerodynamicInput) => engineFetch<Record<string, unknown>>('/v6/simulation/aerodynamics', {
  method: 'POST',
  body: JSON.stringify({ solver: 'integral', ...input }),
});

export const runStructural = (input: StructuralInput) => engineFetch<Record<string, unknown>>('/v6/simulation/structural', {
  method: 'POST',
  body: JSON.stringify({ mode: 'canonical', convergence: true, ...input }),
});

export const runFluidSteady = () => engineFetch<Record<string, unknown>>('/v6/simulation/fluid/steady', {
  method: 'POST',
  body: JSON.stringify({ record: true }),
});

export const runRigidBody = (input: RigidBodyInput = {}) => engineFetch<Record<string, unknown>>('/v6/simulation/rigid-body', {
  method: 'POST',
  body: JSON.stringify({
    object_ids: [],
    force_n: [0, 0, 0],
    torque_nm: [0, 0, 0],
    gravity_m_s2: [0, 0, -9.80665],
    duration_s: 0,
    initial_velocity_m_s: [0, 0, 0],
    initial_angular_velocity_rad_s: [0, 0, 0],
    ...input,
  }),
});
