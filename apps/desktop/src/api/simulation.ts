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

export interface ThermalTransientInput {
  duration_s: number;
  timestep_s: number;
  initial_temperature_c: number;
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

export const fetchSimulationHealth = () => engineFetch<SimulationHealth>('/v6/simulation/health');
export const fetchSimulationGraph = () => engineFetch<SimulationAssemblyGraph>('/v6/simulation/assembly/graph');
export const fetchSimulationRuns = () => engineFetch<SimulationRuns>('/v6/simulation/runs');

export const driveSimulationJoint = (input: JointPoseInput) => engineFetch<Record<string, unknown>>('/v6/simulation/joints/pose', {
  method: 'POST',
  body: JSON.stringify({ ...input, commit: input.commit ?? true }),
});

export const runGravityLoadPath = (gravity: [number, number, number] = [0, 0, -9.80665]) => engineFetch<Record<string, unknown>>('/v6/simulation/joints/gravity-loads', {
  method: 'POST',
  body: JSON.stringify({ gravity_m_s2: gravity }),
});

export const runTransientThermal = (input: ThermalTransientInput) => engineFetch<Record<string, unknown>>('/v6/simulation/thermal/transient', {
  method: 'POST',
  body: JSON.stringify(input),
});

export const runAerodynamics = (input: AerodynamicInput) => engineFetch<Record<string, unknown>>('/v6/simulation/aerodynamics', {
  method: 'POST',
  body: JSON.stringify({ solver: 'integral', ...input }),
});
