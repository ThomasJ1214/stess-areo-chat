import { useCallback, useEffect, useRef, useState } from "react";
import {
  Rocket,
  Box,
  Wind,
  Orbit,
  Layers,
  Activity,
  FlaskConical,
  Upload,
  Download,
  ChevronDown,
  ChevronRight,
  Plus,
  Settings2,
  Play,
  Pause,
  Square,
  Check,
  AlertTriangle,
  X,
  FileBox,
  Link2,
  ArrowRight,
  Info,
  Gauge,
  Target,
  Clock,
  RefreshCw,
  GitCompareArrows,
  SlidersHorizontal,
  Mountain,
  Sparkles,
  ShieldCheck,
  Save,
  Trash2,
  BookOpen,
  PanelLeft,
  PanelRight,
  Maximize2,
  Minimize2,
  MapPinned,
  Globe,
  GraduationCap,
} from "lucide-react";

import Viewport from "./Viewport";
import FlightCharts from "./FlightCharts";
import UserGuide from "./UserGuide";
import Tutorials from "./Tutorial";
import HelpTip from "./HelpTip";
import MotorSearch from "./MotorSearch";
import FlightMap from "./FlightMap";
import WindowDialog from "./WindowDialog";
import { PanelDivider, useWorkspaceLayout } from "./WorkspaceLayout";
import {
  NumberField,
  SIField,
  Toggle,
  Metric,
  Fidelity,
  Empty,
  Chart,
  FieldSelect,
} from "./Controls";
import { request, post, upload, download } from "./api";
import { usePersistentSettings, feaRequestOptions } from "./workspaceSettings";
import { assertValidNumberFields } from "./numericInput";
import type {
  Project,
  Component,
  Material,
  Conditions,
  MeshResponse,
  Workspace,
  Units,
  Overlays,
  Job,
  Configuration,
} from "./types";
import {
  fmt,
  quantity,
  displayValue,
  fromDisplay,
  unitLabel,
  nearestRow,
} from "./units";
import type { Quantity } from "./units";

const workspaces: {
  id: Workspace;
  label: string;
  icon: typeof Box;
  description: string;
}[] = [
  {
    id: "design",
    label: "Design",
    icon: Box,
    description: "Inspect your rocket. Refine the details.",
  },
  {
    id: "aero",
    label: "Aerodynamics",
    icon: Wind,
    description: "Understand stability, drag, and aerodynamic loading.",
  },
  {
    id: "flight",
    label: "Flight",
    icon: Orbit,
    description: "From rail exit to recovery. Every moment matters.",
  },
  {
    id: "structure",
    label: "Structures",
    icon: Layers,
    description: "Explore loads, deformation, and material limits.",
  },
  {
    id: "cfd",
    label: "CFD",
    icon: Activity,
    description: "Resolve compressible flow around your actual geometry.",
  },
  {
    id: "studies",
    label: "Studies",
    icon: FlaskConical,
    description: "Explore the envelope. Compare what changes.",
  },
];
export default function App() {
  const { layout, setLayout, resetLayout } = useWorkspaceLayout();
  const [tutorialTopic, setTutorialTopic] = useState<"app" | Workspace | null>(
    null,
  );
  const [motorSearchProject, setMotorSearchProject] = useState<string | null>(
    null,
  );
  const [mapVisible, setMapVisible] = useState(true);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [gpuDiagnosticsOpen, setGpuDiagnosticsOpen] = useState(false);
  const [automaticAlignment, setAutomaticAlignment] = useState(true);
  const [alignmentOptions, setAlignmentOptions] = useState({
    axis: "auto",
    reverse: false,
    fit_length: false,
    anchor: "start",
  });
  const [alignmentProposal, setAlignmentProposal] = useState<any>(null);
  const [alignmentPending, setAlignmentPending] = useState(false);
  const [alignmentError, setAlignmentError] = useState("");
  const [alignmentGeneration, setAlignmentGeneration] = useState(0);
  const [feaPreflight, setFeaPreflight] = useState<any>(null);
  const [feaPreflightPending, setFeaPreflightPending] = useState(false);
  const [feaPreflightError, setFeaPreflightError] = useState("");
  const launchPlayback = useRef(false);
  const [previousProject, setPreviousProject] = useState<Project | null>(null);
  const [project, setProject] = useState<Project | null>(null),
    [health, setHealth] = useState<any>(null),
    [workspace, setWorkspace] = useState<Workspace>("design");
  const [meshes, setMeshes] = useState<MeshResponse | null>(null),
    [originalMeshes, setOriginalMeshes] = useState<MeshResponse | null>(null),
    [selectedId, setSelectedId] = useState<string | null>(null);
  const [configurationDraft, setConfigurationDraft] =
    useState<Configuration | null>(null);
  const [draft, setDraft] = useState<Component | null>(null),
    [materialDraft, setMaterialDraft] = useState<Material | null>(null);
  const [analysis, setAnalysis] = useState<any>(null),
    [results, setResults] = useState<Record<string, any>>({}),
    [resultJobs, setResultJobs] = useState<Record<string, string>>({}),
    [comparison, setComparison] = useState<any>(null);
  const [job, setJob] = useState<Job | null>(null),
    [jobKind, setJobKind] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [overlays, setOverlays] = useState<Overlays>({
    forces: false,
    markers: true,
    wireframe: false,
    original: false,
    deformation: false,
    pressure: false,
    flow: false,
    stress: false,
  });
  const [fileMenu, setFileMenu] = useState(false),
    [guideOpen, setGuideOpen] = useState(false),
    [designTab, setDesignTab] = useState("component"),
    [cadUnits, setCadUnits] = useState("mm"),
    [assetId, setAssetId] = useState(""),
    [deformationScale, setDeformationScale] = useState(50);
  const [playTime, setPlayTime] = useState(0),
    [playing, setPlaying] = useState(false),
    [playSpeed, setPlaySpeed] = useState(1);
  const settings = usePersistentSettings(
    (saved) =>
      setProject((current) =>
        current?.id === saved.id
          ? {
              ...current,
              analysis_settings: saved.analysis_settings,
            }
          : current,
      ),
    setError,
  );
  const {
    conditions,
    setConditions,
    cfdOptions,
    setCfdOptions,
    feaOptions,
    setFeaOptions,
    studyMode,
    setStudyMode,
    studyOptions,
    setStudyOptions,
  } = settings;
  const restoreSettings = settings.restore;
  const projectIdRef = useRef<string | null>(null);
  const [studyMetric, setStudyMetric] = useState("drag_n");
  const orkInput = useRef<HTMLInputElement>(null),
    projectInput = useRef<HTMLInputElement>(null),
    cadInput = useRef<HTMLInputElement>(null),
    motorInput = useRef<HTMLInputElement>(null),
    polarInput = useRef<HTMLInputElement>(null);
  const fileMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!fileMenu) return;
    const closeOutside = (event: PointerEvent) => {
      if (!fileMenuRef.current?.contains(event.target as Node))
        setFileMenu(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setFileMenu(false);
        fileMenuRef.current
          ?.querySelector<HTMLButtonElement>("button")
          ?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [fileMenu]);
  const units = project?.unit_system || "metric",
    configuration = project?.configurations.find(
      (c) => c.id === project.active_configuration_id,
    ),
    selected = project?.components.find((c) => c.id === selectedId);
  const activeJob = !!job && ["queued", "running"].includes(job.status);
  const flight = results.flight,
    fea = results.fea,
    cfd = results.cfd,
    study = results[studyMode];
  const row = nearestRow(flight?.trajectory || [], playTime);
  const aero = analysis?.aero,
    structural = analysis?.structure;
  const setCondition = (key: keyof Conditions, n: number | null) => {
    setConditions((c) => ({ ...c, [key]: key === "mach" ? n : (n ?? c[key]) }));
    setAnalysis(null);
    setResults({});
    setResultJobs({});
    setComparison(null);
    setPlaying(false);
  };
  const clearResults = () => {
    setAnalysis(null);
    setResults({});
    setResultJobs({});
    setComparison(null);
    setPlaying(false);
    setPlayTime(0);
  };
  const toggleOverlay = (key: keyof Overlays) =>
    setOverlays((o) => ({ ...o, [key]: !o[key] }));
  const operation = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);
  const refreshMeshes = useCallback(async () => {
    const [a, b] = await Promise.all([
      request<MeshResponse>("/mesh"),
      request<MeshResponse>("/mesh?original=true"),
    ]);
    setMeshes(a);
    setOriginalMeshes(b);
  }, []);
  const acceptProject = useCallback(
    async (p: Project, restore = false) => {
      if (restore || projectIdRef.current !== p.id) restoreSettings(p);
      projectIdRef.current = p.id;
      setProject(p);
      setSelectedId((prev) => {
        const savedComponent = p.analysis_settings?.fea_options.component_id;
        if (
          (restore || prev === null) &&
          typeof savedComponent === "string" &&
          p.components.some((c) => c.id === savedComponent)
        )
          return savedComponent;
        return p.components.some((c) => c.id === prev)
          ? prev
          : p.components[0]?.id || null;
      });
      await refreshMeshes();
    },
    [refreshMeshes, restoreSettings],
  );
  useEffect(() => {
    operation(async () => {
      const [h, p] = await Promise.all([
        request("/health"),
        request<Project>("/project"),
      ]);
      setHealth(h);
      await acceptProject(p);
    });
  }, [operation, acceptProject]);
  useEffect(() => {
    setConfigurationDraft(
      configuration ? structuredClone(configuration) : null,
    );
  }, [configuration]);
  useEffect(() => {
    setDraft(selected ? structuredClone(selected) : null);
    const mat = project?.materials.find((m) => m.id === selected?.material_id);
    setMaterialDraft(mat ? structuredClone(mat) : null);
    setAssetId(selected?.asset_id || project?.assets[0]?.id || "");
  }, [selected, project?.materials, project?.assets]);
  useEffect(() => {
    if (!selectedId) return;
    setFeaOptions((current) => {
      if (current.component_id !== selectedId)
        return {
          ...current,
          component_id: selectedId,
          clamp_type:
            selected?.geometry_mode !== "replacement" &&
            [
              "fin",
              "finset",
              "trapezoidfinset",
              "freeformfinset",
              "ellipticalfinset",
            ].includes(selected?.kind || "")
              ? "radial_root"
              : "plane",
        };
      if (
        selected?.geometry_mode === "replacement" &&
        current.clamp_type === "radial_root"
      )
        return { ...current, clamp_type: "plane" };
      return current;
    });
  }, [selectedId, selected?.geometry_mode]);
  useEffect(() => {
    setAutomaticAlignment(!selected?.asset_id || selected.asset_id !== assetId);
    setAlignmentOptions({
      axis: "auto",
      reverse: false,
      fit_length: false,
      anchor: "start",
    });
  }, [selectedId, selected?.asset_id, assetId]);
  useEffect(() => {
    setAlignmentProposal(null);
    setAlignmentError("");
    if (
      workspace !== "design" ||
      designTab !== "geometry" ||
      !selected ||
      !assetId ||
      !automaticAlignment
    ) {
      setAlignmentPending(false);
      return;
    }
    let disposed = false;
    setAlignmentPending(true);
    const timer = setTimeout(async () => {
      try {
        const proposal = await post<any>("/geometry/alignment", {
          component_id: selected.id,
          asset_id: assetId,
          ...alignmentOptions,
          include_mesh: true,
        });
        if (disposed) return;
        setAlignmentProposal(proposal);
        setDraft((current) =>
          current?.id === selected.id
            ? { ...current, transform: proposal.transform }
            : current,
        );
      } catch (err) {
        if (!disposed)
          setAlignmentError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!disposed) setAlignmentPending(false);
      }
    }, 200);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [
    workspace,
    designTab,
    selected,
    assetId,
    automaticAlignment,
    alignmentOptions,
    alignmentGeneration,
  ]);
  useEffect(() => {
    setFeaPreflight(null);
    setFeaPreflightError("");
    if (workspace !== "structure" || !selected) {
      setFeaPreflightPending(false);
      return;
    }
    let disposed = false;
    setFeaPreflightPending(true);
    const timer = setTimeout(async () => {
      try {
        const check = await post<any>("/fea/preflight", {
          component_id: selected.id,
          options: {
            mesh_size: feaOptions.mesh_size,
            max_elements: feaOptions.max_elements,
          },
        });
        if (disposed) return;
        setFeaPreflight(check);
        if (
          feaOptions.auto_mesh &&
          check.recommended_within_budget &&
          check.recommended_mesh_size_m > 0 &&
          Math.abs(check.recommended_mesh_size_m - feaOptions.mesh_size) >
            check.recommended_mesh_size_m * 1e-8
        )
          setFeaOptions((current) => ({
            ...current,
            mesh_size: check.recommended_mesh_size_m,
          }));
      } catch (err) {
        if (!disposed)
          setFeaPreflightError(
            err instanceof Error ? err.message : String(err),
          );
      } finally {
        if (!disposed) setFeaPreflightPending(false);
      }
    }, 200);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [
    workspace,
    selected,
    project?.materials,
    feaOptions.mesh_size,
    feaOptions.max_elements,
    feaOptions.auto_mesh,
  ]);
  useEffect(() => {
    if (!activeJob || !job) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Job>(`/jobs/${job.id}`);
        if (disposed) return;
        setJob(next);
        if (
          (next.status === "completed" ||
            (jobKind === "cfd" && next.status === "cancelled")) &&
          next.result
        ) {
          setResults((r) => ({
            ...r,
            [jobKind]: { ...next.result, job_status: next.status },
          }));
          setResultJobs((r) => ({ ...r, [jobKind]: next.id }));
          if (jobKind === "flight") {
            setOverlays((o) => ({ ...o, stress: true, forces: true }));
            setPlayTime(0);
            setPlaying(launchPlayback.current);
            launchPlayback.current = false;
          }
          if (jobKind === "fea")
            setOverlays((o) => ({ ...o, stress: true, deformation: false }));
          if (jobKind === "cfd")
            setOverlays((o) => ({ ...o, flow: true, pressure: true }));
          if (jobKind === "comparison") setComparison(next.result);
          if (jobKind === "sweep" || jobKind === "monte_carlo") {
            const key = Object.keys(next.result.statistics || {})[0];
            if (key) setStudyMetric(key);
          }
        }
        if (["failed", "cancelled"].includes(next.status))
          launchPlayback.current = false;
        if (next.status === "failed")
          setError(next.error || "Simulation failed.");
        if (["queued", "running"].includes(next.status))
          timer = setTimeout(poll, 700);
      } catch (e) {
        if (!disposed) {
          setError(`Job status: ${e instanceof Error ? e.message : String(e)}`);
          timer = setTimeout(poll, 2000);
        }
      }
    };
    timer = setTimeout(poll, 300);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [activeJob, job?.id, jobKind]);
  useEffect(() => {
    if (!playing || !flight?.trajectory?.length) return;
    let last = performance.now();
    const timer = setInterval(() => {
      const now = performance.now(),
        delta = ((now - last) / 1000) * playSpeed;
      last = now;
      setPlayTime((t) => {
        const max = flight.trajectory.at(-1).time;
        if (t + delta >= max) {
          setPlaying(false);
          return max;
        }
        return t + delta;
      });
    }, 40);
    return () => clearInterval(timer);
  }, [playing, flight, playSpeed]);
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(""), 4500);
      return () => clearTimeout(timer);
    }
  }, [notice]);
  async function saveProject(p: Project) {
    await settings.flush();
    const restore = p.id !== projectIdRef.current;
    const savedProject = restore
      ? p
      : { ...p, analysis_settings: settings.getSettings() };
    await acceptProject(
      await request<Project>("/project", {
        method: "PUT",
        body: JSON.stringify(savedProject),
      }),
      restore,
    );
    if (p.unit_system === project?.unit_system) {
      clearResults();
    }
  }
  function importFile(kind: string, file: File | undefined) {
    if (!file) return;
    if (activeJob) {
      setError(
        "Wait for or cancel the current simulation before importing a project or asset.",
      );
      return;
    }
    operation(async () => {
      await settings.flush();
      if (kind === "ork") {
        await acceptProject(await upload<Project>("/import/ork", file), true);
        clearResults();
        setWorkspace("design");
        setNotice(
          "OpenRocket project imported. Review import warnings and motor assignments.",
        );
      } else if (kind === "project") {
        await acceptProject(await upload<Project>("/project/load", file), true);
        clearResults();
        setNotice("Project loaded.");
      } else if (kind === "cad") {
        const asset: any = await upload("/import/geometry", file, {
          units: cadUnits,
        });
        await acceptProject(await request<Project>("/project"));
        setAssetId(asset.id);
        setDesignTab("geometry");
        setNotice(
          `${file.name} imported. Select a component and attach its geometry.`,
        );
      } else if (kind === "polar") {
        await acceptProject(await upload<Project>("/import/polar", file));
        clearResults();
        setNotice(
          "User-supplied aerodynamic polar imported for this exact geometry and configuration. Verify provenance and physical validity.",
        );
      } else {
        await upload("/import/motor", file);
        await acceptProject(await request<Project>("/project"));
        setDesignTab("configuration");
        setNotice("Motor curve imported. Assign it to a flight configuration.");
      }
    });
  }
  function startJob(
    kind: string,
    options: Record<string, unknown> = {},
    autoPlayback = false,
  ) {
    if (activeJob) return;
    operation(async () => {
      assertValidNumberFields();
      await settings.flush();
      const next = await post<Job>("/jobs", {
        kind,
        conditions,
        configuration_id: project?.active_configuration_id,
        options: kind === "fea" ? feaRequestOptions(options) : options,
      });
      if (kind === "flight") {
        launchPlayback.current = autoPlayback;
        if (autoPlayback) {
          setPlaying(false);
          setPlayTime(0);
          setResults((current) => {
            const changed = { ...current };
            delete changed.flight;
            return changed;
          });
        }
      }
      setJobKind(kind);
      setJob(next);
    });
  }
  function launch() {
    if (!canRun) return;
    startJob("flight", {}, true);
  }
  function runAnalysis() {
    operation(async () => {
      assertValidNumberFields();
      await settings.flush();
      setAnalysis(
        await post("/analyze", {
          conditions,
          configuration_id: project?.active_configuration_id,
        }),
      );
      setNotice(
        "Engineering estimates completed. Review solver assumptions below.",
      );
    });
  }
  function runCompare() {
    operation(async () => {
      assertValidNumberFields();
      await settings.flush();
      setComparison(
        await post("/compare", {
          conditions,
          configuration_id: project?.active_configuration_id,
        }),
      );
    });
  }
  function exportResult(kind: string, format: string) {
    const id = resultJobs[kind];
    if (id)
      operation(async () =>
        download(
          `/jobs/${id}/export?format=${format}`,
          `${project?.name || "rocket"}-${kind}.${format}`,
        ),
      );
  }
  function exportRunProject(kind: string) {
    const id = resultJobs[kind];
    if (id)
      operation(async () =>
        download(
          `/jobs/${id}/project`,
          `${project?.name || "rocket"}-${kind}-inputs.rocket.json`,
        ),
      );
  }
  function applyComponent() {
    if (!draft || !project) return;
    operation(async () => {
      assertValidNumberFields();
      await saveProject({
        ...project,
        components: project.components.map((c) =>
          c.id === draft.id ? draft : c,
        ),
      });
      setNotice(
        "Component saved. Rerun affected simulations to refresh results.",
      );
    });
  }
  function applyMaterial() {
    if (!materialDraft || !project) return;
    operation(async () => {
      assertValidNumberFields();
      await saveProject({
        ...project,
        materials: project.materials.map((m) =>
          m.id === materialDraft.id ? materialDraft : m,
        ),
      });
      setNotice("Material properties saved.");
    });
  }
  function changeConfig(key: string, value: unknown) {
    setConfigurationDraft((c) => (c ? { ...c, [key]: value } : c));
  }
  const loadDemo = () =>
    operation(async () => {
      if (activeJob)
        throw new Error(
          "Wait for or cancel the current simulation before creating a project.",
        );
      await settings.flush();
      await acceptProject(await post<Project>("/project/demo"), true);
      clearResults();
      setNotice(
        "Reference rocket created with a demonstration motor. Replace it with your measured motor data.",
      );
    });
  const canRun = !busy && !activeJob && !!project?.components.length;
  const conditionFields = (
    <>
      <div className="field-pair">
        <SIField
          label="Primary stream speed"
          kind="speed"
          units={units}
          value={conditions.speed}
          onChange={(n) => setCondition("speed", n)}
          min={0}
          max={1000}
        />
        <NumberField
          label="Mach override"
          value={conditions.mach}
          onChange={(n) => setCondition("mach", n)}
          min={0}
          max={2}
          hint="Optional. A value overrides airspeed using local speed of sound. Clear to use airspeed."
        />
      </div>
      <div className="field-pair">
        <SIField
          label="Altitude"
          kind="length"
          units={units}
          value={conditions.altitude}
          onChange={(n) => setCondition("altitude", n)}
          min={-500}
          max={50000}
        />
        <NumberField
          label="Angle of attack"
          value={conditions.angle_of_attack}
          onChange={(n) => setCondition("angle_of_attack", n)}
          unit="°"
          min={-45}
          max={45}
        />
      </div>
      <div className="field-pair">
        <SIField
          label="Lateral wind"
          kind="speed"
          units={units}
          value={conditions.wind_speed}
          onChange={(n) => setCondition("wind_speed", n)}
          min={0}
          max={150}
        />
        <NumberField
          label="Wind direction"
          value={conditions.wind_direction}
          onChange={(n) => setCondition("wind_direction", n)}
          unit="°"
          min={0}
          max={360}
        />
      </div>
      <div className="field-pair">
        <NumberField
          label="Turbulence"
          value={conditions.turbulence * 100}
          onChange={(n) => n !== null && setCondition("turbulence", n / 100)}
          unit="%"
          min={0}
          max={100}
        />
        <NumberField
          label="Sideslip"
          value={conditions.sideslip}
          onChange={(n) => setCondition("sideslip", n)}
          unit="°"
          min={-45}
          max={45}
        />
      </div>
      <NumberField
        label="Temperature deviation from ISA"
        value={conditions.temperature_delta}
        onChange={(n) => setCondition("temperature_delta", n)}
        unit="K"
        min={-80}
        max={80}
      />
    </>
  );
  return (
    <div className="app-shell">
      <input
        ref={polarInput}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={(e) => {
          importFile("polar", e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        ref={orkInput}
        type="file"
        accept=".ork"
        className="hidden"
        onChange={(e) => {
          importFile("ork", e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        ref={projectInput}
        type="file"
        accept=".json,.rocket"
        className="hidden"
        onChange={(e) => {
          importFile("project", e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        ref={cadInput}
        type="file"
        accept=".step,.stp,.stl,.obj,.ply"
        className="hidden"
        onChange={(e) => {
          importFile("cad", e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        ref={motorInput}
        type="file"
        accept=".eng,.rse"
        className="hidden"
        onChange={(e) => {
          importFile("motor", e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <header className="topbar">
        <a className="brand" href="#" onClick={(e) => e.preventDefault()}>
          <img
            className="brand-icon"
            src="/icon.svg"
            alt=""
            width="34"
            height="34"
          />
          <span>
            ROCKET<span className="brand-second">WORKBENCH</span>
          </span>
          <span className="version">0.2.0</span>
        </a>
        <div className="topbar-divider" />
        <div className="project-label">
          <FileBox size={15} />
          <span>{project?.name || "Connecting to local engine…"}</span>
        </div>
        <div className="header-actions">
          <button className="quiet-btn" onClick={() => setTutorialTopic("app")}>
            <GraduationCap size={16} /> Getting started
          </button>
          <button
            className="quiet-btn"
            onClick={() => setGuideOpen(true)}
            title="Open bundled offline instructions"
          >
            <BookOpen size={15} /> User guide
          </button>
          {previousProject && (
            <button
              className="quiet-btn"
              disabled={busy || activeJob}
              onClick={() =>
                operation(async () => {
                  await saveProject(previousProject);
                  setPreviousProject(null);
                  setNotice("Previous project restored.");
                })
              }
            >
              <RefreshCw size={14} /> Undo new project
            </button>
          )}
          <select
            aria-label="Unit system"
            className="units-select"
            value={units}
            disabled={!project || busy || activeJob}
            onChange={(e) =>
              project &&
              operation(() =>
                saveProject({
                  ...project,
                  unit_system: e.target.value as Units,
                }),
              )
            }
          >
            <option value="metric">SI / Metric</option>
            <option value="us">US Customary</option>
          </select>
          <button
            className="quiet-btn"
            onClick={() =>
              operation(async () => {
                await settings.flush();
                await download(
                  "/project/download",
                  `${project?.name || "project"}.rocket.json`,
                );
              })
            }
            disabled={!project || busy || activeJob}
            title="Save complete project, including imported geometry"
          >
            <Save size={15} /> Save project
          </button>
          <div className="file-actions" ref={fileMenuRef}>
            <button
              className="primary muted"
              onClick={() => setFileMenu((x) => !x)}
              disabled={busy || activeJob}
              aria-expanded={fileMenu}
              aria-controls="import-menu"
            >
              <Upload size={15} /> Import <ChevronDown size={12} />
            </button>
            {fileMenu && (
              <div className="dropdown" id="import-menu">
                <button
                  onClick={() => {
                    orkInput.current?.click();
                    setFileMenu(false);
                  }}
                >
                  OpenRocket .ork
                </button>
                <button
                  onClick={() => {
                    projectInput.current?.click();
                    setFileMenu(false);
                  }}
                >
                  Saved project .json
                </button>
                <button
                  onClick={() => {
                    cadInput.current?.click();
                    setFileMenu(false);
                  }}
                >
                  CAD / 3D geometry
                </button>
                <button
                  onClick={() => {
                    motorInput.current?.click();
                    setFileMenu(false);
                  }}
                >
                  Motor curve .eng / .rse
                </button>
                <button
                  onClick={() => {
                    if (project) setMotorSearchProject(project.id);
                    setFileMenu(false);
                  }}
                >
                  <Globe size={15} /> Find motor online
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <nav className="workspace-nav">
        {workspaces.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={workspace === id ? "active" : ""}
            onClick={() => {
              setWorkspace(id);
              if (id === "aero") setOverlays((o) => ({ ...o, forces: true }));
            }}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
        <div className="local-status">
          <span className={`live-dot ${health ? "" : "offline"}`} />
          {health ? "LOCAL ENGINE" : "CONNECTING"}
          <button
            className="compute-status"
            aria-label="GPU diagnostics"
            onClick={() => setGpuDiagnosticsOpen(true)}
          >
            {health?.capabilities?.gpu_compute
              ? "CUDA available"
              : "CPU solver · GPU viewport"}
          </button>
        </div>
      </nav>
      <div className="workspace-window-bar" aria-label="Workspace windows">
        <div className="window-actions">
          <button
            aria-label={
              layout.assembly && !layout.focus
                ? "Hide assembly"
                : "Show assembly"
            }
            aria-pressed={layout.assembly && !layout.focus}
            onClick={() =>
              setLayout((current) => ({
                ...current,
                focus: false,
                assembly: current.focus || !current.assembly,
              }))
            }
          >
            <PanelLeft size={16} />
            <span>Assembly</span>
          </button>
          <button
            aria-label={
              layout.setup && !layout.focus ? "Hide setup" : "Show setup"
            }
            aria-pressed={layout.setup && !layout.focus}
            onClick={() =>
              setLayout((current) => ({
                ...current,
                focus: false,
                setup: current.focus || !current.setup,
              }))
            }
          >
            <PanelRight size={16} />
            <span>{workspace === "design" ? "Inspector" : "Setup"}</span>
          </button>
          <button
            aria-label={layout.focus ? "Exit focus view" : "Focus 3D view"}
            aria-pressed={layout.focus}
            onClick={() =>
              setLayout((current) => ({ ...current, focus: !current.focus }))
            }
          >
            {layout.focus ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            <span>Focus view</span>
          </button>
          <button onClick={resetLayout}>
            <RefreshCw size={14} /> Reset layout
          </button>
          {workspace === "flight" && (
            <button
              aria-pressed={mapVisible}
              onClick={() => {
                const stage =
                  document.querySelector<HTMLElement>(".viewport-stage");
                if (stage && stage.clientHeight < 280) setMapExpanded(true);
                else setMapVisible((value) => !value);
              }}
            >
              <MapPinned size={16} /> Flight map
            </button>
          )}
        </div>
        <button
          className="page-tutorial"
          aria-label="Tutorial"
          onClick={() => {
            setPlaying(false);
            setTutorialTopic(workspace);
          }}
        >
          <GraduationCap size={16} /> Tutorial{" "}
          <span>{workspaces.find((w) => w.id === workspace)?.label}</span>
        </button>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {notice && (
        <div className="notice-banner" role="status">
          <Check size={15} />
          {notice}
          <button
            aria-label="Dismiss notification"
            onClick={() => setNotice("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div
        className="main-layout"
        data-assembly-open={layout.assembly && !layout.focus}
        data-setup-open={layout.setup && !layout.focus}
        data-focus={layout.focus}
        style={
          {
            "--assembly-width": `${layout.assemblyWidth}px`,
            "--setup-width": `${layout.setupWidth}px`,
          } as React.CSSProperties
        }
      >
        <aside
          className="project-sidebar"
          aria-label="Rocket assembly"
          hidden={!layout.assembly || layout.focus}
        >
          <div className="section-heading">
            <span>ROCKET ASSEMBLY</span>
            <span className="count">{project?.components.length || 0}</span>
          </div>
          <div className="configuration-selector">
            <label>Flight configuration</label>
            <select
              aria-label="Flight configuration"
              value={project?.active_configuration_id || ""}
              disabled={!project || busy || activeJob}
              onChange={(e) =>
                project &&
                operation(() =>
                  saveProject({
                    ...project,
                    active_configuration_id: e.target.value,
                  }),
                )
              }
            >
              {project?.configurations.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <div className="configuration-note">
              <span className="live-dot" />
              {configuration?.recovery_defined === false
                ? "Recovery settings missing"
                : configuration?.deployment === "dual"
                  ? "Dual deployment"
                  : "Single deployment"}
              <button
                title="Edit configuration"
                onClick={() => {
                  setWorkspace("design");
                  setDesignTab("configuration");
                }}
              >
                <Settings2 size={12} />
              </button>
            </div>
          </div>
          <div className="assembly-root">
            <Rocket size={15} />
            <strong>{project?.name || "New rocket"}</strong>
          </div>
          <div className="component-tree">
            {project?.components.map((c) => (
              <button
                key={c.id}
                className={`component-row ${selectedId === c.id ? "selected" : ""} ${!c.enabled ? "disabled-component" : ""}`}
                onClick={() => setSelectedId(c.id)}
                style={{ paddingLeft: c.parent_id ? 24 : 14 }}
              >
                <span className="tree-branch" />
                <Box size={13} />
                <span>{c.name}</span>
                {c.geometry_mode === "replacement" && (
                  <Link2 size={12} className="cad-badge" />
                )}
              </button>
            ))}
            {!project?.components.length && (
              <div className="sidebar-empty">
                Your assembly will appear here.
                <button
                  className="quiet-btn"
                  onClick={() => orkInput.current?.click()}
                >
                  <Upload size={14} /> Import .ork
                </button>
                <button
                  className="quiet-btn"
                  onClick={loadDemo}
                  disabled={busy || activeJob}
                >
                  <Plus size={14} /> Example rocket
                </button>
              </div>
            )}
          </div>
          <div className="sidebar-bottom">
            <div className="asset-library">
              <div className="section-heading">
                <span>GEOMETRY LIBRARY</span>
                <span className="count">{project?.assets.length || 0}</span>
              </div>
              {project?.assets.map((a) => (
                <button
                  key={a.id}
                  onClick={() => {
                    setAssetId(a.id);
                    setDesignTab("geometry");
                    setWorkspace("design");
                  }}
                >
                  <FileBox size={13} />
                  <span>{a.name}</span>
                  <small>{a.format}</small>
                </button>
              ))}
              <button
                className="add-asset"
                onClick={() => cadInput.current?.click()}
                disabled={busy || activeJob}
              >
                <Plus size={14} /> Import geometry
              </button>
            </div>
            <div className="scope-note">
              <Info size={14} />
              <span>
                Passive high-power rockets
                <br />
                <strong>Up to Mach 2 · 12 ft envelope</strong>
              </span>
            </div>
          </div>
        </aside>
        <PanelDivider
          label="Resize assembly panel"
          value={layout.assemblyWidth}
          min={190}
          max={380}
          onChange={(assemblyWidth) =>
            setLayout((current) => ({ ...current, assemblyWidth }))
          }
        />
        <main
          className="workspace-main"
          style={{
            gridTemplateRows: layout.focus
              ? "auto minmax(0, 1fr)"
              : `auto minmax(150px, ${layout.sceneRatio}fr) 8px minmax(130px, 1fr)`,
          }}
        >
          <div className="workspace-title">
            <div>
              <div className="eyebrow">
                ENGINEERING WORKSPACE <span>/</span>{" "}
                {workspaces
                  .find((w) => w.id === workspace)
                  ?.label.toUpperCase()}
              </div>
              <h1>
                {workspace === "design"
                  ? "Your rocket. In every detail."
                  : workspaces.find((w) => w.id === workspace)?.description}
              </h1>
              <p>
                {workspace === "design"
                  ? "Combine flight-ready OpenRocket designs with the geometry that makes them real."
                  : workspace === "cfd"
                    ? "Experimental inviscid Euler solver · local execution · actual mesh and flow fields"
                    : workspace === "structure"
                      ? "Beam and fin estimates + isotropic linear static tetrahedral FEA"
                      : "Transparent calculations. Useful insights. Explicit limitations."}
              </p>
              <HelpTip
                term={
                  workspace === "cfd"
                    ? "CFD"
                    : workspace === "structure"
                      ? "FEA"
                      : workspace === "studies"
                        ? "Parameter sweep"
                        : workspace === "flight"
                          ? "AGL"
                          : "CG"
                }
              />
            </div>
            {workspace === "flight" ? (
              <div className="launch-actions">
                <button
                  className="launch-button"
                  aria-label="Launch"
                  disabled={!canRun}
                  onClick={launch}
                >
                  <Rocket size={23} /> Launch
                </button>
                <small>
                  {activeJob && jobKind === "flight"
                    ? "Calculating flight · playback starts when ready"
                    : flight
                      ? "Launch again to recalculate · drag to adjust camera"
                      : "On launch rail · check motor and recovery"}
                </small>
              </div>
            ) : (
              <span className="scope-chip">
                <span className="live-dot" />{" "}
                {workspace === "cfd"
                  ? "EXPERIMENTAL SOLVER"
                  : workspace === "structure"
                    ? "LINEAR ELASTIC"
                    : "DESIGN & ANALYSIS"}
              </span>
            )}
          </div>
          <div className="viewport-wrapper viewport-stage">
            <Viewport
              meshes={meshes}
              originalMeshes={originalMeshes}
              selectedId={selectedId}
              alignmentPreview={alignmentProposal?.preview_mesh || null}
              onSelect={setSelectedId}
              overlays={overlays}
              aero={aero}
              flightRow={workspace === "flight" ? row : null}
              fea={workspace === "structure" ? fea : null}
              cfd={workspace === "cfd" ? cfd : null}
              deformationScale={deformationScale}
              workspace={workspace}
              trajectory={flight?.trajectory || []}
              units={units}
              launchConditions={flight?.inputs?.conditions || conditions}
              playing={playing}
              launchReady={!flight}
              flightEvents={flight?.events || []}
            />
            {workspace === "flight" && mapVisible && !mapExpanded && (
              <div className="flight-map-overlay">
                <header className="flight-map-window-top">
                  <MapPinned size={14} />
                  <strong>FLIGHT MAP</strong>
                  <button
                    aria-label="Expand flight map"
                    onClick={() => setMapExpanded(true)}
                  >
                    <Maximize2 size={14} />
                  </button>
                  <button
                    aria-label="Hide flight map"
                    onClick={() => setMapVisible(false)}
                  >
                    <X size={14} />
                  </button>
                </header>
                <FlightMap
                  projectId={project?.id}
                  trajectory={flight?.trajectory || []}
                  events={flight?.events || []}
                  flightRow={row}
                  conditions={flight?.inputs?.conditions || conditions}
                  units={units}
                  onSeek={(time) => {
                    setPlayTime(time);
                    setPlaying(false);
                  }}
                />
              </div>
            )}
            <div className="view-toolbar">
              <div className="toolbar-group">
                <span>OVERLAYS</span>
                <Toggle
                  label="CG / CP"
                  value={overlays.markers}
                  onChange={() => toggleOverlay("markers")}
                />
                <Toggle
                  label="Forces"
                  value={overlays.forces}
                  onChange={() => toggleOverlay("forces")}
                  disabled={workspace === "flight" ? !row : !aero}
                />
                <Toggle
                  label="Wireframe"
                  value={overlays.wireframe}
                  onChange={() => toggleOverlay("wireframe")}
                />
                <Toggle
                  label="Original geometry"
                  value={overlays.original}
                  onChange={() => toggleOverlay("original")}
                  disabled={!project?.assets.length}
                />
              </div>
              {workspace === "flight" && (
                <div className="toolbar-group">
                  <Toggle
                    label="Estimated component stress"
                    value={overlays.stress}
                    onChange={() => toggleOverlay("stress")}
                    disabled={!row?.structural_components?.length}
                  />
                </div>
              )}
              {workspace === "structure" && (
                <div className="toolbar-group">
                  <Toggle
                    label="Stress"
                    value={overlays.stress}
                    onChange={() => toggleOverlay("stress")}
                    disabled={!fea}
                  />
                  <Toggle
                    label="Deformation"
                    value={overlays.deformation}
                    onChange={() => toggleOverlay("deformation")}
                    disabled={!fea}
                  />
                </div>
              )}
              {workspace === "cfd" && (
                <div className="toolbar-group">
                  <Toggle
                    label="Pressure"
                    value={overlays.pressure}
                    onChange={() => toggleOverlay("pressure")}
                    disabled={!cfd}
                  />
                  <Toggle
                    label="Velocity"
                    value={overlays.flow}
                    onChange={() => toggleOverlay("flow")}
                    disabled={!cfd}
                  />
                </div>
              )}
            </div>
          </div>
          <PanelDivider
            label="Resize 3D view"
            orientation="horizontal"
            value={layout.sceneRatio}
            min={0.6}
            max={3}
            onChange={(sceneRatio) =>
              setLayout((current) => ({ ...current, sceneRatio }))
            }
          />
          <section
            className="workspace-results"
            aria-label="Results and flight playback"
            hidden={layout.focus}
          >
            {activeJob && (
              <div className="job-progress">
                <div className="job-top">
                  <div>
                    <span className="spinner" />
                    <strong>{jobKind.replace("_", " ").toUpperCase()}</strong>
                    <span>{job?.message}</span>
                  </div>
                  <button
                    onClick={() =>
                      operation(async () => {
                        await post(`/jobs/${job?.id}/cancel`);
                      })
                    }
                  >
                    <Square size={12} /> Cancel
                  </button>
                </div>
                <div
                  role="progressbar"
                  aria-label={`${jobKind.replaceAll("_", " ")} progress`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={
                    job?.progress_basis === "convergence_unknown"
                      ? undefined
                      : Math.round((job?.progress || 0) * 100)
                  }
                  className={`progress-track ${job?.progress_basis === "convergence_unknown" ? "indeterminate" : ""}`}
                >
                  <div
                    style={{
                      width: `${Math.max(0, Math.min(1, job?.progress || 0)) * 100}%`,
                    }}
                  />
                </div>
                <div className="job-meta">
                  <span>
                    {job?.progress_basis === "convergence_unknown"
                      ? "Convergence pending · completion time unknown"
                      : `${fmt((job?.progress || 0) * 100, 0)}% ${job?.progress_basis === "budget_usage" ? "budget used" : "complete"}`}
                  </span>
                  <span>
                    Elapsed {fmt(job?.elapsed_seconds, 0)}s ·{" "}
                    {job?.progress_basis === "budget_usage"
                      ? "Budget ETA"
                      : "ETA"}{" "}
                    {job?.eta_seconds === null
                      ? job?.progress_basis === "convergence_unknown"
                        ? "unknown"
                        : "calculating…"
                      : `${fmt(job?.eta_seconds, 0)}s`}
                  </span>
                </div>
              </div>
            )}
            {workspace === "design" && (
              <>
                <div className="design-summary">
                  <div className="section-heading">
                    <span>DESIGN OVERVIEW</span>
                    <button onClick={runAnalysis} disabled={!canRun}>
                      <RefreshCw size={12} /> Calculate
                    </button>
                  </div>
                  <div className="metrics-row">
                    <Metric
                      label="Loaded mass"
                      value={
                        aero
                          ? displayValue(aero.mass_kg, "mass", units)
                          : undefined
                      }
                      unit={unitLabel("mass", units)}
                    />
                    <Metric
                      label="Center of gravity"
                      value={
                        aero
                          ? displayValue(aero.cg_m, "length", units)
                          : undefined
                      }
                      unit={unitLabel("length", units)}
                      color="#e3b777"
                    />
                    <Metric
                      label="Center of pressure"
                      value={
                        typeof aero?.cp_m === "number"
                          ? displayValue(aero.cp_m, "length", units)
                          : undefined
                      }
                      unit={unitLabel("length", units)}
                      color="#71c8c1"
                    />
                    <Metric
                      label="Static margin"
                      value={aero?.stability_calibers}
                      unit="cal"
                    />
                    <Metric
                      label="Components"
                      value={project?.components.length}
                      unit="parts"
                    />
                  </div>
                </div>
                <div className="design-callout">
                  <span className="callout-icon">
                    <Link2 size={18} />
                  </span>
                  <div>
                    <strong>Flight design meets real geometry.</strong>
                    <p>
                      Select a component, import your STEP or STL file, then
                      align and attach it in Geometry. Keep the original shape
                      available for comparison.
                    </p>
                  </div>
                  <button onClick={() => setDesignTab("geometry")}>
                    Geometry tools <ArrowRight size={14} />
                  </button>
                </div>
                {(project?.import_warnings?.length || 0) > 0 && (
                  <div className="warning-list">
                    <AlertTriangle size={15} />
                    <div>
                      <strong>Import notes</strong>
                      {project?.import_warnings.map((w, i) => (
                        <p key={i}>{w}</p>
                      ))}
                    </div>
                  </div>
                )}
                <Fidelity data={aero} />
              </>
            )}
            {workspace === "aero" && (
              <div className="analysis-results">
                <div className="section-heading">
                  <span>AERODYNAMIC RESULTS</span>
                  <span className="result-tag">
                    {aero ? "EMPIRICAL ESTIMATE" : "READY TO ANALYZE"}
                  </span>
                </div>
                {aero ? (
                  <>
                    {aero.cp_valid === false && (
                      <div className="warning-list">
                        <AlertTriangle size={15} />
                        <div>
                          <strong>
                            Center of pressure and stability are outside this
                            model's validity.
                          </strong>
                          <p>
                            Barrowman stability is provisional outside
                            small-angle subsonic flow and does not resolve
                            external CAD. A validated geometry-specific
                            aerodynamic polar can supply coefficients. Review
                            all warnings before interpreting results.
                          </p>
                        </div>
                      </div>
                    )}
                    <div className="metrics-row">
                      <Metric label="Drag coefficient" value={aero.cd} />
                      <Metric
                        label="Drag force"
                        value={displayValue(aero.drag_n, "force", units)}
                        unit={unitLabel("force", units)}
                      />
                      <Metric
                        label="Normal force"
                        value={displayValue(
                          aero.normal_force_n,
                          "force",
                          units,
                        )}
                        unit={unitLabel("force", units)}
                      />
                      <Metric
                        label="Resultant airspeed"
                        value={displayValue(aero.speed_m_s, "speed", units)}
                        unit={unitLabel("speed", units)}
                      />
                      <Metric
                        label="Dynamic pressure"
                        value={displayValue(
                          aero.dynamic_pressure_pa,
                          "pressure",
                          units,
                        )}
                        unit={unitLabel("pressure", units)}
                      />
                      <Metric
                        label="Static margin"
                        value={aero.stability_calibers}
                        unit="cal"
                        color={
                          aero.stability_calibers < 1 ? "#ed927e" : "#75cabe"
                        }
                      />
                    </div>
                    <Fidelity data={aero} />
                    <div className="phase-row">
                      <span>
                        Effective incidence:{" "}
                        {fmt(aero.effective_angle_of_attack_deg)}° AoA ·{" "}
                        {fmt(aero.effective_sideslip_deg)}° sideslip · Force
                        arrows use schematic lengths.
                      </span>
                    </div>
                    {aero.component_breakdown_valid === false && (
                      <div className="warning-list">
                        <AlertTriangle size={15} />
                        <div>
                          <strong>
                            Component drag breakdown is unavailable for the
                            imported whole-rocket polar.
                          </strong>
                          <p>
                            The table shows reference-model contributions; they
                            do not sum to the supplied-polar total.
                          </p>
                        </div>
                      </div>
                    )}
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Component</th>
                            <th>Mass</th>
                            <th>Drag / coefficient</th>
                            <th>Normal load</th>
                          </tr>
                        </thead>
                        <tbody>
                          {aero.components?.map((c: any, i: number) => (
                            <tr
                              key={i}
                              onClick={() =>
                                setSelectedId(c.component_id || c.id)
                              }
                            >
                              <td>
                                {c.name ||
                                  project?.components.find(
                                    (p) => p.id === c.component_id,
                                  )?.name ||
                                  c.kind}
                              </td>
                              <td>
                                {quantity(c.mass_kg ?? c.mass, "mass", units)}
                              </td>
                              <td>
                                {typeof c.drag_n === "number"
                                  ? quantity(c.drag_n, "force", units)
                                  : fmt(
                                      c.cd ??
                                        c.cd_contribution ??
                                        c.drag_coefficient,
                                      4,
                                    )}
                              </td>
                              <td>
                                {quantity(c.normal_force_n, "force", units)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <Empty icon={Wind} title="Make the invisible measurable.">
                    Set your test conditions and run an aerodynamic analysis to
                    see drag, stability, center of pressure, and component
                    loading.
                  </Empty>
                )}
              </div>
            )}
            {workspace === "flight" && (
              <div className="flight-results">
                {flight ? (
                  <>
                    <div className="playback">
                      <button
                        className="play-button"
                        aria-label={
                          playing
                            ? "Pause flight playback"
                            : "Play flight playback"
                        }
                        onClick={() => {
                          if (playTime >= flight.trajectory.at(-1)?.time)
                            setPlayTime(0);
                          setPlaying((p) => !p);
                        }}
                      >
                        {playing ? <Pause size={17} /> : <Play size={17} />}
                      </button>
                      <div className="timeline">
                        <div className="timeline-label">
                          <span>FLIGHT PLAYBACK</span>
                          <strong>
                            {fmt(playTime, 2)} <small>s</small>
                            <span>
                              / {fmt(flight.trajectory.at(-1)?.time, 1)} s
                            </span>
                          </strong>
                        </div>
                        <input
                          type="range"
                          aria-label="Flight timeline"
                          min={0}
                          max={flight.trajectory.at(-1)?.time || 1}
                          step={0.01}
                          value={playTime}
                          onChange={(e) => {
                            setPlayTime(Number(e.target.value));
                            setPlaying(false);
                          }}
                        />
                        <div className="event-markers">
                          {flight.events?.map((e: any, i: number) => (
                            <button
                              key={i}
                              title={`${e.name} at ${fmt(e.time)} s`}
                              onClick={() => {
                                setPlayTime(e.time);
                                setPlaying(false);
                              }}
                            >
                              <span
                                style={{
                                  background: i % 2 ? "#72c9c1" : "#ddae73",
                                }}
                              />
                              {e.name.replaceAll("_", " ")}{" "}
                              <small>{fmt(e.time, 1)}s</small>
                            </button>
                          ))}
                        </div>
                      </div>
                      <select
                        aria-label="Playback speed"
                        value={playSpeed}
                        onChange={(e) => setPlaySpeed(Number(e.target.value))}
                      >
                        {[0.25, 1, 2, 5, 10].map((s) => (
                          <option value={s} key={s}>
                            {s}×
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="metrics-row">
                      <Metric
                        label="Altitude"
                        value={
                          row
                            ? displayValue(row.altitude, "length", units)
                            : undefined
                        }
                        unit={unitLabel("length", units)}
                      />
                      <Metric
                        label="Velocity"
                        value={
                          row
                            ? displayValue(row.velocity, "speed", units)
                            : undefined
                        }
                        unit={unitLabel("speed", units)}
                      />
                      <Metric
                        label="Acceleration"
                        value={
                          row
                            ? displayValue(
                                row.acceleration,
                                "acceleration",
                                units,
                              )
                            : undefined
                        }
                        unit={unitLabel("acceleration", units)}
                      />
                      <Metric label="Mach" value={row?.mach} />
                      <Metric
                        label="Dynamic pressure"
                        value={
                          row
                            ? displayValue(
                                row.dynamic_pressure,
                                "pressure",
                                units,
                              )
                            : undefined
                        }
                        unit={unitLabel("pressure", units)}
                      />
                      <Metric
                        label="Estimated flight stress"
                        value={
                          row?.stress != null
                            ? displayValue(row.stress, "stress", units)
                            : undefined
                        }
                        unit={unitLabel("stress", units)}
                      />
                    </div>
                    <div className="phase-row">
                      <span className="phase-badge">{row?.phase}</span>
                      <span>
                        Stability {fmt(row?.stability)} cal · Thrust{" "}
                        {quantity(row?.thrust, "force", units)} · Drag{" "}
                        {quantity(row?.drag, "force", units)} · Mass{" "}
                        {quantity(row?.mass, "mass", units)}
                      </span>
                    </div>
                    <FlightCharts
                      trajectory={flight.trajectory}
                      units={units}
                      time={playTime}
                    />
                    <Fidelity data={flight} currentConditions={conditions} />
                    <div className="export-row">
                      <button onClick={() => exportResult("flight", "csv")}>
                        <Download size={14} /> Flight data CSV
                      </button>
                      <button onClick={() => exportResult("flight", "html")}>
                        <Download size={14} /> Engineering report
                      </button>
                      <button onClick={() => exportRunProject("flight")}>
                        <FileBox size={14} /> Run input project
                      </button>
                    </div>
                  </>
                ) : (
                  <Empty
                    icon={Orbit}
                    title="The complete flight, at your fingertips."
                  >
                    Assign a motor curve and recovery configuration, set your
                    launch conditions, then simulate. Scrub the timeline to
                    inspect rail exit, burnout, maximum Q, apogee, and
                    deployment.
                  </Empty>
                )}
              </div>
            )}
            {workspace === "structure" && (
              <div className="analysis-results">
                <div className="section-heading">
                  <span>STRUCTURAL RESULTS</span>
                  <button onClick={runAnalysis} disabled={!canRun}>
                    <RefreshCw size={12} /> Beam / fin estimates
                  </button>
                </div>
                {structural ? (
                  <>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Component</th>
                            <th>Stress</th>
                            <th>Deflection</th>
                            <th>Safety factor</th>
                          </tr>
                        </thead>
                        <tbody>
                          {structural.components?.map((c: any, i: number) => (
                            <tr
                              key={i}
                              onClick={() => setSelectedId(c.component_id)}
                            >
                              <td>{c.name}</td>
                              <td>
                                {c.supported === false
                                  ? "Unavailable"
                                  : quantity(c.stress_pa, "stress", units)}
                              </td>
                              <td>
                                {c.supported === false
                                  ? "Unavailable"
                                  : quantity(
                                      c.deflection_m,
                                      "length",
                                      units,
                                      5,
                                    )}
                              </td>
                              <td
                                className={
                                  typeof c.safety_factor === "number" &&
                                  c.safety_factor < 1
                                    ? "danger-text"
                                    : ""
                                }
                              >
                                {fmt(c.safety_factor)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Fidelity data={structural} />
                  </>
                ) : (
                  <Empty icon={Layers} title="Understand the load path.">
                    Run beam and fin estimates for fast screening, or select a
                    mesh component and run tetrahedral finite element analysis
                    with an explicit clamp and load.
                  </Empty>
                )}
                {fea && (
                  <>
                    <div className="section-heading">
                      <span>FINITE ELEMENT SOLUTION</span>
                      <span className="result-tag">ACTUAL SOLVER FIELD</span>
                    </div>
                    <div className="metrics-row">
                      <Metric
                        label="Peak von Mises"
                        value={displayValue(
                          fea.summary?.max_von_mises_pa ??
                            (fea.von_mises_pa || [0]).reduce(
                              (a: number, b: number) => Math.max(a, b),
                              0,
                            ),
                          "stress",
                          units,
                        )}
                        unit={unitLabel("stress", units)}
                      />
                      <Metric
                        label="Maximum displacement"
                        value={displayValue(
                          fea.summary?.max_displacement_m,
                          "length",
                          units,
                        )}
                        unit={unitLabel("length", units)}
                      />
                      <Metric label="Nodes" value={fea.vertices?.length} />
                      <Metric
                        label="Tetrahedra"
                        value={fea.tetrahedra?.length}
                      />
                      <Metric
                        label="Safety factor"
                        value={fea.summary?.safety_factor}
                      />
                      <Metric
                        label="Strain energy"
                        value={displayValue(
                          fea.summary?.strain_energy_j,
                          "energy",
                          units,
                        )}
                        unit={unitLabel("energy", units)}
                      />
                      <Metric
                        label="Equilibrium residual"
                        value={fea.summary?.relative_equilibrium_residual}
                      />
                    </div>
                    <Fidelity
                      data={fea}
                      currentConditions={conditions}
                      currentOptions={feaRequestOptions(feaOptions)}
                    />
                    {fea.summary?.cfd_pressure_transfer && (
                      <div className="warning-list">
                        <Info size={15} />
                        <div>
                          <strong>One-way CFD pressure transfer</strong>
                          <p>
                            Mapped surface:{" "}
                            {fmt(
                              fea.summary.cfd_pressure_transfer
                                .mapped_surface_area_fraction * 100,
                              1,
                            )}
                            % · Mean transfer distance:{" "}
                            {quantity(
                              fea.summary.cfd_pressure_transfer
                                .mean_transfer_distance_m,
                              "length",
                              units,
                              5,
                            )}{" "}
                            · Maximum:{" "}
                            {quantity(
                              fea.summary.cfd_pressure_transfer
                                .max_transfer_distance_m,
                              "length",
                              units,
                              5,
                            )}
                          </p>
                        </div>
                      </div>
                    )}
                    <div className="export-row">
                      <button onClick={() => exportResult("fea", "json")}>
                        <Download size={14} /> Full solver data
                      </button>
                      <button onClick={() => exportResult("fea", "html")}>
                        <Download size={14} /> FEA report
                      </button>
                      <button onClick={() => exportRunProject("fea")}>
                        <FileBox size={14} /> Run input project
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
            {workspace === "cfd" && (
              <div className="analysis-results">
                <div className="section-heading">
                  <span>FLOW SOLUTION</span>
                  <span className="result-tag">EXPERIMENTAL · INVISCID</span>
                </div>
                {cfd ? (
                  <>
                    <div className="metrics-row">
                      <Metric
                        label={
                          cfd.summary?.converged
                            ? "Inviscid pressure drag"
                            : "Partial pressure force"
                        }
                        value={displayValue(
                          cfd.summary?.pressure_drag_n,
                          "force",
                          units,
                        )}
                        unit={unitLabel("force", units)}
                      />
                      <Metric
                        label="Grid cells"
                        value={cfd.summary?.cell_count}
                      />
                      <Metric label="Time steps" value={cfd.summary?.steps} />
                      <Metric
                        label="Flow time"
                        value={cfd.summary?.physical_time_s}
                        unit="s"
                      />
                      <Metric
                        label="Convergence"
                        value={
                          cfd.summary?.converged ? "Reached" : "Not reached"
                        }
                        color={cfd.summary?.converged ? "#71c8be" : "#e0b176"}
                      />
                      <Metric
                        label="Stop reason"
                        value={String(
                          cfd.summary?.status || "unknown",
                        ).replaceAll("_", " ")}
                        color="#e0b176"
                      />
                    </div>
                    {!cfd.summary?.converged && (
                      <div className="engineering-note">
                        <AlertTriangle size={16} />
                        <p>
                          This is a partial flow field. Its pressure force is
                          not a converged steady-flow prediction. Review the
                          stop reason and residual history before continuing.
                        </p>
                      </div>
                    )}
                    <div
                      className="solver-readiness"
                      aria-label="CFD run diagnostics"
                    >
                      <h4>Run diagnostics</h4>
                      <p>
                        Actual calculation: <strong>{cfd.backend}</strong> ·{" "}
                        {fmt(cfd.summary?.measured_steps_per_second, 1)} steps/s
                      </p>
                      <p>
                        Domain crossings:{" "}
                        {fmt(cfd.summary?.domain_crossings_completed, 3)} ·
                        minimum convergence flow time{" "}
                        {fmt(cfd.summary?.minimum_convergence_time_s, 5)} s{" "}
                        {cfd.summary?.minimum_convergence_time_reached
                          ? "reached"
                          : "not reached"}
                        .
                      </p>
                      {cfd.summary?.estimated_seconds_to_minimum_flow_time !=
                        null && (
                        <p>
                          Measured-speed estimate to minimum flow time:{" "}
                          {fmt(
                            cfd.summary.estimated_seconds_to_minimum_flow_time,
                            0,
                          )}{" "}
                          computer seconds. Residual convergence can take
                          longer; this is not an accuracy guarantee.
                        </p>
                      )}
                      {cfd.summary?.median_solid_cross_section_cells && (
                        <p>
                          Median body cross-section:{" "}
                          {cfd.summary.median_solid_cross_section_cells
                            .map((n: number) => fmt(n, 1))
                            .join(" × ")}{" "}
                          cells. Thin fins may need more resolution.
                        </p>
                      )}
                    </div>
                    <Fidelity
                      data={cfd}
                      currentConditions={conditions}
                      currentOptions={cfdOptions}
                    />
                    {cfd.summary?.aerodynamic_geometry_policy && (
                      <div className="warning-list">
                        <Info size={15} />
                        <div>
                          <strong>Exterior flow geometry</strong>
                          <p>{cfd.summary.aerodynamic_geometry_policy}</p>
                          <p>
                            Exterior fluid cells:{" "}
                            {fmt(cfd.summary.exterior_fluid_cells, 0)}
                            {" · "}Enclosed nonflow cells:{" "}
                            {fmt(cfd.summary.enclosed_nonflow_cells, 0)}
                            {" · "}Source material mesh{" "}
                            {cfd.summary.source_material_mesh_modified === false
                              ? "preserved"
                              : "see run inputs"}
                            . Nonflow cells describe the flow mask, not material
                            volume.
                          </p>
                        </div>
                      </div>
                    )}
                    <div className="chart-card">
                      <h4>Convergence residuals · iteration history</h4>
                      <Chart
                        data={cfd.history || []}
                        x="step"
                        series={[
                          {
                            key: "residual",
                            label: "Conservation",
                            color: "#76c6c2",
                          },
                          {
                            key: "wall_pressure_residual",
                            label: "Wall pressure",
                            color: "#e0b176",
                          },
                          {
                            key: "force_residual",
                            label: "Force",
                            color: "#92aee4",
                          },
                          {
                            key: "moment_residual",
                            label: "Moment",
                            color: "#c498da",
                          },
                        ]}
                      />
                    </div>
                    <div className="export-row">
                      <button onClick={() => exportResult("cfd", "json")}>
                        <Download size={14} /> Flow solution JSON
                      </button>
                      <button onClick={() => exportResult("cfd", "html")}>
                        <Download size={14} /> CFD report
                      </button>
                      <button onClick={() => exportRunProject("cfd")}>
                        <FileBox size={14} /> Run input project
                      </button>
                    </div>
                  </>
                ) : (
                  <Empty
                    icon={Activity}
                    title="Explore flow around actual geometry."
                  >
                    The Cartesian Euler solver computes inviscid compressible
                    flow on a voxel grid. Display arrows and pressure samples
                    from computed fields. This solver does not predict skin
                    friction, turbulence, or validated transonic drag.
                  </Empty>
                )}
              </div>
            )}
            {workspace === "studies" && (
              <div className="studies-results">
                <div className="section-heading">
                  <span>DESIGN EXPLORATION</span>
                  <div className="segmented small">
                    {["sweep", "monte_carlo", "comparison"].map((m) => (
                      <button
                        key={m}
                        className={studyMode === m ? "active" : ""}
                        onClick={() => setStudyMode(m)}
                      >
                        {m === "sweep"
                          ? "Parameter sweep"
                          : m === "monte_carlo"
                            ? "Monte Carlo"
                            : "Compare"}
                      </button>
                    ))}
                  </div>
                </div>
                {studyMode === "comparison" ? (
                  comparison ? (
                    <>
                      <Fidelity data={comparison} />
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Quantity</th>
                              <th>Original geometry</th>
                              <th>Current geometry</th>
                              <th>Change</th>
                            </tr>
                          </thead>
                          <tbody>
                            {[
                              { key: "mass_kg", label: "Mass", kind: "mass" },
                              {
                                key: "cg_m",
                                label: "Center of gravity",
                                kind: "length",
                              },
                              {
                                key: "cp_m",
                                label: "Center of pressure",
                                kind: "length",
                              },
                              {
                                key: "stability_calibers",
                                label: "Stability · cal",
                              },
                              { key: "cd", label: "Drag coefficient" },
                              {
                                key: "drag_n",
                                label: "Drag force",
                                kind: "force",
                              },
                            ].map((k) => (
                              <tr key={k.key}>
                                <td>{k.label}</td>
                                <td>
                                  {k.kind
                                    ? quantity(
                                        comparison.original?.aero?.[k.key],
                                        k.kind as Quantity,
                                        units,
                                      )
                                    : fmt(comparison.original?.aero?.[k.key])}
                                </td>
                                <td>
                                  {k.kind
                                    ? quantity(
                                        comparison.replacement?.aero?.[k.key],
                                        k.kind as Quantity,
                                        units,
                                      )
                                    : fmt(
                                        comparison.replacement?.aero?.[k.key],
                                      )}
                                </td>
                                <td className="accent-text">
                                  {k.kind
                                    ? quantity(
                                        comparison.deltas?.[k.key],
                                        k.kind as Quantity,
                                        units,
                                      )
                                    : fmt(comparison.deltas?.[k.key])}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {comparison.original?.cfd && (
                        <>
                          <div className="metrics-row">
                            <Metric
                              label={
                                comparison.original.cfd.summary.converged
                                  ? "Original CFD pressure drag"
                                  : "Original partial pressure force"
                              }
                              value={displayValue(
                                comparison.original.cfd.summary.pressure_drag_n,
                                "force",
                                units,
                              )}
                              unit={unitLabel("force", units)}
                            />
                            <Metric
                              label={
                                comparison.replacement.cfd.summary.converged
                                  ? "Current CFD pressure drag"
                                  : "Current partial pressure force"
                              }
                              value={displayValue(
                                comparison.replacement.cfd.summary
                                  .pressure_drag_n,
                                "force",
                                units,
                              )}
                              unit={unitLabel("force", units)}
                            />
                          </div>
                          <div className="engineering-note">
                            <AlertTriangle size={15} />
                            <p>
                              Original CFD:{" "}
                              {comparison.original.cfd.summary.converged
                                ? "numerically converged"
                                : "not converged"}{" "}
                              ({comparison.original.cfd.summary.status}).
                              Current CFD:{" "}
                              {comparison.replacement.cfd.summary.converged
                                ? "numerically converged"
                                : "not converged"}{" "}
                              ({comparison.replacement.cfd.summary.status}).
                              Pressure forces are experimental and unvalidated;
                              they exclude skin friction.
                            </p>
                          </div>
                        </>
                      )}
                      {(comparison.original?.flight ||
                        comparison.replacement?.flight) && (
                        <>
                          <div className="section-heading">
                            <span>GEOMETRY FLIGHT PERFORMANCE</span>
                          </div>
                          <div className="table-wrap">
                            <table>
                              <thead>
                                <tr>
                                  <th>Quantity</th>
                                  <th>Original geometry</th>
                                  <th>Current geometry</th>
                                  <th>Change</th>
                                </tr>
                              </thead>
                              <tbody>
                                {[
                                  {
                                    key: "apogee_m",
                                    label: "Apogee AGL",
                                    kind: "length",
                                  },
                                  {
                                    key: "max_velocity_m_s",
                                    label: "Maximum velocity",
                                    kind: "speed",
                                  },
                                  {
                                    key: "max_dynamic_pressure_pa",
                                    label: "Maximum Q",
                                    kind: "pressure",
                                  },
                                  {
                                    key: "max_stress_pa",
                                    label: "Estimated maximum stress",
                                    kind: "stress",
                                  },
                                  {
                                    key: "rail_exit_velocity_m_s",
                                    label: "Rail exit velocity",
                                    kind: "speed",
                                  },
                                ].map((k) => (
                                  <tr key={k.key}>
                                    <td>{k.label}</td>
                                    <td>
                                      {quantity(
                                        comparison.original?.flight?.summary?.[
                                          k.key
                                        ],
                                        k.kind as Quantity,
                                        units,
                                      )}
                                    </td>
                                    <td>
                                      {quantity(
                                        comparison.replacement?.flight
                                          ?.summary?.[k.key],
                                        k.kind as Quantity,
                                        units,
                                      )}
                                    </td>
                                    <td>
                                      {quantity(
                                        comparison.flight_deltas?.[k.key],
                                        k.kind as Quantity,
                                        units,
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <p className="microcopy">
                            Point-mass trajectories use each geometry's declared
                            coefficient source. CAD mass changes apply;
                            arbitrary surface drag changes require a
                            geometry-bound supplied polar. Flight stress remains
                            a quasi-static estimate.
                          </p>
                        </>
                      )}
                      <div className="section-heading">
                        <span>FLIGHT CONFIGURATION COMPARISON</span>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Configuration</th>
                              <th>Loaded mass</th>
                              <th>Static margin</th>
                              <th>Drag</th>
                            </tr>
                          </thead>
                          <tbody>
                            {comparison.configurations?.map((c: any) => (
                              <tr key={c.configuration_id}>
                                <td>{c.name}</td>
                                {c.aero ? (
                                  <>
                                    <td>
                                      {quantity(c.aero.mass_kg, "mass", units)}
                                    </td>
                                    <td>
                                      {fmt(c.aero.stability_calibers)} cal
                                    </td>
                                    <td>
                                      {quantity(c.aero.drag_n, "force", units)}
                                    </td>
                                  </>
                                ) : (
                                  <td colSpan={3}>
                                    {c.error || "Configuration unavailable"}
                                  </td>
                                )}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    <Empty
                      icon={GitCompareArrows}
                      title="See the impact of real geometry."
                    >
                      Compare original OpenRocket geometry with attached CAD
                      replacements. Empirical calculations retain explicit
                      geometry validity limits; use the optional CFD comparison
                      to resolve shape differences.
                    </Empty>
                  )
                ) : study ? (
                  <>
                    <Fidelity
                      data={study}
                      currentConditions={conditions}
                      currentOptions={studyOptions}
                    />
                    <label className="inline-select">
                      Plot metric
                      <select
                        value={studyMetric}
                        onChange={(e) => setStudyMetric(e.target.value)}
                      >
                        {Object.keys(study.statistics || {}).map((k) => (
                          <option key={k} value={k}>
                            {k.replaceAll("_", " ")}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="chart-card">
                      <h4>
                        {study.parameter.replaceAll("_", " ")} vs{" "}
                        {studyMetric.replaceAll("_", " ")} · SI values
                      </h4>
                      <Chart
                        data={[...study.rows].sort((a, b) => a.value - b.value)}
                        x="value"
                        series={[
                          {
                            key: studyMetric,
                            label: studyMetric,
                            color: "#7acac0",
                          },
                        ]}
                        height={190}
                      />
                    </div>
                    <div className="metrics-row">
                      <Metric
                        label="Completed samples"
                        value={study.rows.length}
                      />
                      <Metric
                        label="Mean"
                        value={study.statistics?.[studyMetric]?.mean}
                      />
                      <Metric
                        label="Standard deviation"
                        value={study.statistics?.[studyMetric]?.std}
                      />
                      <Metric
                        label="5th percentile"
                        value={study.statistics?.[studyMetric]?.p05}
                      />
                      <Metric
                        label="95th percentile"
                        value={study.statistics?.[studyMetric]?.p95}
                      />
                    </div>
                    {study.failures?.length > 0 && (
                      <div className="warning-list">
                        <AlertTriangle size={15} />
                        <div>
                          <strong>
                            {study.failures.length} excluded samples
                          </strong>
                          {study.failures.map((f: any, i: number) => (
                            <p key={i}>
                              Sample {f.index}: {f.error}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="export-row">
                      <button onClick={() => exportResult(studyMode, "csv")}>
                        <Download size={14} /> Study CSV
                      </button>
                      <button onClick={() => exportResult(studyMode, "html")}>
                        <Download size={14} /> Study report
                      </button>
                      <button onClick={() => exportRunProject(studyMode)}>
                        <FileBox size={14} /> Run input project
                      </button>
                    </div>
                  </>
                ) : (
                  <Empty
                    icon={FlaskConical}
                    title="Build confidence across the envelope."
                  >
                    Sweep speed, Mach, wind, altitude, or angle of attack. Run a
                    reproducible Monte Carlo study to quantify input sensitivity
                    using the same documented solver assumptions.
                  </Empty>
                )}
              </div>
            )}
          </section>
        </main>
        <PanelDivider
          label="Resize setup panel"
          value={layout.setupWidth}
          min={280}
          max={480}
          reverse
          onChange={(setupWidth) =>
            setLayout((current) => ({ ...current, setupWidth }))
          }
        />
        <aside
          className="inspector"
          aria-label="Design and simulation setup"
          hidden={!layout.setup || layout.focus}
        >
          <fieldset
            key={`${settings.restoreGeneration}:${workspace}:${workspace === "design" ? selectedId : ""}`}
            className="inspector-lock"
            disabled={busy || activeJob}
            aria-label="Project and simulation settings"
          >
            <div className="inspector-header">
              <SlidersHorizontal size={16} />
              <strong>
                {workspace === "design"
                  ? "DESIGN INSPECTOR"
                  : "SIMULATION SETUP"}
              </strong>
              <span className="count">
                {workspace === "design" ? "01" : "SI"}
              </span>
            </div>
            {workspace === "design" ? (
              <>
                <div className="inspector-tabs">
                  {["component", "geometry", "configuration"].map((t) => (
                    <button
                      key={t}
                      className={designTab === t ? "active" : ""}
                      onClick={() => setDesignTab(t)}
                    >
                      {t === "configuration"
                        ? "Flight setup"
                        : t[0].toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                </div>
                {designTab === "component" && (
                  <div className="inspector-body">
                    {draft ? (
                      <>
                        <div className="selected-heading">
                          <span className="part-icon">
                            <Box size={19} />
                          </span>
                          <div>
                            <h3>{draft.name}</h3>
                            <span>{draft.kind.toUpperCase()}</span>
                          </div>
                        </div>
                        <label className="field">
                          <span>Component name</span>
                          <input
                            value={draft.name}
                            onChange={(e) =>
                              setDraft({ ...draft, name: e.target.value })
                            }
                          />
                        </label>
                        <div className="field-pair">
                          <SIField
                            label="Axial position"
                            kind="length"
                            units={units}
                            value={draft.x}
                            onChange={(n) =>
                              n !== null && setDraft({ ...draft, x: n })
                            }
                          />
                          <SIField
                            label="Length"
                            kind="length"
                            units={units}
                            value={draft.length}
                            onChange={(n) =>
                              n !== null && setDraft({ ...draft, length: n })
                            }
                          />
                        </div>
                        <div className="field-pair">
                          <SIField
                            label="Radius"
                            kind="length"
                            units={units}
                            value={draft.radius}
                            onChange={(n) =>
                              n !== null && setDraft({ ...draft, radius: n })
                            }
                          />
                          <SIField
                            label="Wall thickness"
                            kind="length"
                            units={units}
                            value={draft.thickness}
                            onChange={(n) =>
                              n !== null && setDraft({ ...draft, thickness: n })
                            }
                          />
                        </div>
                        {draft.kind.includes("fin") && (
                          <>
                            <div className="field-pair">
                              <NumberField
                                label="Fin count"
                                value={draft.fin_count}
                                onChange={(n) =>
                                  n !== null &&
                                  setDraft({ ...draft, fin_count: n })
                                }
                                min={1}
                                max={16}
                                step={1}
                              />
                              <SIField
                                label="Span"
                                kind="length"
                                units={units}
                                value={draft.span}
                                onChange={(n) =>
                                  n !== null && setDraft({ ...draft, span: n })
                                }
                              />
                            </div>
                            <div className="field-pair">
                              <SIField
                                label="Root chord"
                                kind="length"
                                units={units}
                                value={draft.root_chord}
                                onChange={(n) =>
                                  n !== null &&
                                  setDraft({ ...draft, root_chord: n })
                                }
                              />
                              <SIField
                                label="Tip chord"
                                kind="length"
                                units={units}
                                value={draft.tip_chord}
                                onChange={(n) =>
                                  n !== null &&
                                  setDraft({ ...draft, tip_chord: n })
                                }
                              />
                            </div>
                            <SIField
                              label="Sweep distance"
                              kind="length"
                              units={units}
                              value={draft.sweep}
                              onChange={(n) =>
                                n !== null && setDraft({ ...draft, sweep: n })
                              }
                            />
                          </>
                        )}
                        <div className="panel-divider" />
                        <div className="subheading">MASS PROPERTIES</div>
                        <SIField
                          label="Mass override (optional)"
                          kind="mass"
                          units={units}
                          value={draft.mass_override}
                          onChange={(n) =>
                            setDraft({ ...draft, mass_override: n })
                          }
                        />
                        <SIField
                          label="Local CG override (optional)"
                          kind="length"
                          units={units}
                          value={draft.cg_override}
                          onChange={(n) =>
                            setDraft({ ...draft, cg_override: n })
                          }
                        />
                        <FieldSelect
                          label="Material"
                          value={draft.material_id || ""}
                          onChange={(v) => {
                            setDraft({ ...draft, material_id: v || null });
                            const m = project?.materials.find(
                              (m) => m.id === v,
                            );
                            setMaterialDraft(m ? structuredClone(m) : null);
                          }}
                        >
                          <option value="">Default material</option>
                          {project?.materials.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                        </FieldSelect>
                        <div className="toggle-row">
                          <Toggle
                            label="Enabled"
                            value={draft.enabled}
                            onChange={() =>
                              setDraft({ ...draft, enabled: !draft.enabled })
                            }
                          />
                          <Toggle
                            label="External surface"
                            value={draft.external}
                            onChange={() =>
                              setDraft({ ...draft, external: !draft.external })
                            }
                          />
                        </div>
                        <button
                          className="primary wide"
                          onClick={applyComponent}
                          disabled={busy}
                        >
                          <Check size={14} /> Apply component changes
                        </button>
                        {materialDraft && (
                          <details className="material-editor">
                            <summary>
                              Custom material properties{" "}
                              <ChevronDown size={13} />
                            </summary>
                            <label className="field">
                              <span>Material name</span>
                              <input
                                value={materialDraft.name}
                                onChange={(e) =>
                                  setMaterialDraft({
                                    ...materialDraft,
                                    name: e.target.value,
                                  })
                                }
                              />
                            </label>
                            <SIField
                              label="Density"
                              kind="density"
                              units={units}
                              value={materialDraft.density}
                              onChange={(n) =>
                                n !== null &&
                                setMaterialDraft({
                                  ...materialDraft,
                                  density: n,
                                })
                              }
                            />
                            <SIField
                              label="Young's modulus"
                              kind="stress"
                              units={units}
                              value={materialDraft.youngs_modulus}
                              onChange={(n) =>
                                n !== null &&
                                setMaterialDraft({
                                  ...materialDraft,
                                  youngs_modulus: n,
                                })
                              }
                            />
                            <SIField
                              label="Yield strength"
                              kind="stress"
                              units={units}
                              value={materialDraft.yield_strength}
                              onChange={(n) =>
                                n !== null &&
                                setMaterialDraft({
                                  ...materialDraft,
                                  yield_strength: n,
                                })
                              }
                            />
                            <NumberField
                              label="Poisson ratio"
                              value={materialDraft.poisson_ratio}
                              onChange={(n) =>
                                n !== null &&
                                setMaterialDraft({
                                  ...materialDraft,
                                  poisson_ratio: n,
                                })
                              }
                              min={-0.99}
                              max={0.49}
                            />
                            <label className="field">
                              <span>Material assumptions</span>
                              <textarea
                                value={materialDraft.description}
                                onChange={(e) =>
                                  setMaterialDraft({
                                    ...materialDraft,
                                    description: e.target.value,
                                  })
                                }
                              />
                            </label>
                            <p className="microcopy">
                              Isotropic material model. Composite laminate
                              failure requires a separate validated model.
                            </p>
                            <button
                              className="secondary wide"
                              onClick={applyMaterial}
                              disabled={busy}
                            >
                              Save material
                            </button>
                          </details>
                        )}
                      </>
                    ) : (
                      <Empty icon={Box} title="Select a component">
                        Choose a part in the assembly or click it in the 3D
                        viewport.
                      </Empty>
                    )}
                  </div>
                )}
                {designTab === "geometry" && (
                  <div className="inspector-body">
                    <div className="selected-heading">
                      <span className="part-icon">
                        <Link2 size={19} />
                      </span>
                      <div>
                        <h3>Detailed geometry</h3>
                        <span>REPLACE · ALIGN · COMPARE</span>
                      </div>
                    </div>
                    <p className="panel-intro">
                      Attach real CAD to{" "}
                      <strong>{draft?.name || "a selected component"}</strong>.
                      Automatic alignment centers it on the part's axis and
                      places its front at the selected part's front. Only this
                      part is replaced.
                    </p>
                    <div className="field-pair">
                      <FieldSelect
                        label="Mesh file units"
                        value={cadUnits}
                        onChange={setCadUnits}
                      >
                        {["mm", "cm", "m", "in", "ft"].map((u) => (
                          <option key={u}>{u}</option>
                        ))}
                      </FieldSelect>
                      <div className="field import-field">
                        <span>STEP / STL / mesh</span>
                        <button
                          className="secondary"
                          onClick={() => cadInput.current?.click()}
                          disabled={busy}
                        >
                          <Upload size={13} /> Import
                        </button>
                      </div>
                    </div>
                    <FieldSelect
                      label="Geometry asset"
                      value={assetId}
                      onChange={setAssetId}
                    >
                      <option value="">Select imported geometry</option>
                      {project?.assets.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </FieldSelect>
                    <button
                      className="secondary wide"
                      disabled={!assetId || busy}
                      onClick={() =>
                        operation(async () => {
                          await settings.flush();
                          setPreviousProject(
                            project
                              ? {
                                  ...structuredClone(project),
                                  analysis_settings: settings.getSettings(),
                                }
                              : null,
                          );
                          await download(
                            "/project/download",
                            `${project?.name || "project"}-before-cad.rocket.json`,
                          );
                          await acceptProject(
                            await post<Project>("/geometry/standalone", {
                              asset_id: assetId,
                            }),
                          );
                          clearResults();
                          setNotice(
                            "New CAD-only project created. Previous project backup requested; Undo new project remains available this session. Assign a motor and import valid geometry-specific aerodynamic coefficients.",
                          );
                        })
                      }
                    >
                      <FileBox size={14} /> New project from CAD
                    </button>
                    {project?.assets.find((a) => a.id === assetId) && (
                      <div className="asset-info">
                        <span>
                          {project.assets
                            .find((a) => a.id === assetId)
                            ?.faces.length.toLocaleString()}{" "}
                          triangles
                        </span>
                        <span>
                          {project.assets.find((a) => a.id === assetId)
                            ?.watertight
                            ? "Watertight"
                            : "Open surface"}
                        </span>
                        {project.assets
                          .find((a) => a.id === assetId)
                          ?.warnings.map((w, i) => (
                            <p key={i}>{w}</p>
                          ))}
                      </div>
                    )}
                    {draft && (
                      <>
                        <p className="microcopy">
                          STEP units come from the CAD document; the unit
                          selector controls STL and other mesh formats.
                        </p>
                        <div className="subheading">ALIGNMENT</div>
                        <Toggle
                          label="Automatic alignment"
                          value={automaticAlignment}
                          onChange={() =>
                            setAutomaticAlignment(!automaticAlignment)
                          }
                        />
                        {automaticAlignment && (
                          <>
                            <div className="field-pair">
                              <FieldSelect
                                label="Source axis"
                                value={alignmentOptions.axis}
                                onChange={(axis) =>
                                  setAlignmentOptions({
                                    ...alignmentOptions,
                                    axis,
                                  })
                                }
                              >
                                <option value="auto">
                                  Automatic · principal axis
                                </option>
                                <option value="x">CAD X</option>
                                <option value="y">CAD Y</option>
                                <option value="z">CAD Z</option>
                              </FieldSelect>
                              <FieldSelect
                                label="Placement anchor"
                                value={alignmentOptions.anchor}
                                onChange={(anchor) =>
                                  setAlignmentOptions({
                                    ...alignmentOptions,
                                    anchor,
                                  })
                                }
                              >
                                <option value="start">
                                  Front of selected part
                                </option>
                                <option value="center">
                                  Center of selected part
                                </option>
                              </FieldSelect>
                            </div>
                            <Toggle
                              label="Reverse direction"
                              value={alignmentOptions.reverse}
                              onChange={() =>
                                setAlignmentOptions({
                                  ...alignmentOptions,
                                  reverse: !alignmentOptions.reverse,
                                })
                              }
                            />
                            <Toggle
                              label="Fit selected length"
                              value={alignmentOptions.fit_length}
                              onChange={() =>
                                setAlignmentOptions({
                                  ...alignmentOptions,
                                  fit_length: !alignmentOptions.fit_length,
                                })
                              }
                            />
                            <p className="microcopy">
                              Physical CAD dimensions are preserved by default.
                              Fit selected length uniformly scales all
                              dimensions and changes material volume and mass.
                            </p>
                            <button
                              className="secondary wide"
                              disabled={!assetId || alignmentPending || busy}
                              onClick={() =>
                                setAlignmentGeneration((n) => n + 1)
                              }
                            >
                              <RefreshCw size={14} /> Preview automatic
                              alignment
                            </button>
                            {alignmentPending && (
                              <p role="status">Calculating CAD placement…</p>
                            )}
                            {alignmentError && (
                              <p className="danger-text" role="alert">
                                {alignmentError}
                              </p>
                            )}
                            {alignmentProposal && (
                              <div
                                className="solver-readiness"
                                aria-label="CAD alignment preview"
                              >
                                <h4>Placement preview</h4>
                                <p>
                                  Amber geometry previews the selected
                                  replacement. Axis:{" "}
                                  {alignmentProposal.source_axis
                                    ?.map((n: number) => fmt(n, 2))
                                    .join(", ")}{" "}
                                  · scale {fmt(alignmentProposal.scale, 4)}.
                                </p>
                                {alignmentProposal.interfaces?.map(
                                  (item: any, i: number) => (
                                    <p key={i}>
                                      {item.neighbor_name}: {item.status}
                                      {item.axial_separation_m != null
                                        ? ` · ${quantity(Math.abs(item.axial_separation_m), "length", units)}`
                                        : ""}
                                    </p>
                                  ),
                                )}
                                {alignmentProposal.warnings?.map(
                                  (warning: string, i: number) => (
                                    <p
                                      key={`warning-${i}`}
                                      className="warning-text"
                                    >
                                      {warning}
                                    </p>
                                  ),
                                )}
                                <p>
                                  The rest of the assembly and source CAD remain
                                  unchanged. Aligned touching parts form the
                                  exterior flow assembly; structural joints and
                                  Boolean unions are not inferred.
                                </p>
                              </div>
                            )}
                          </>
                        )}
                        <div className="triple-fields">
                          {["X", "Y", "Z"].map((axis, i) => (
                            <SIField
                              key={axis}
                              label={`${axis} offset`}
                              kind="length"
                              units={units}
                              value={draft.transform.translation[i]}
                              onChange={(n) => {
                                if (n === null) return;
                                setAutomaticAlignment(false);
                                const t = [...draft.transform.translation];
                                t[i] = n;
                                setDraft({
                                  ...draft,
                                  transform: {
                                    ...draft.transform,
                                    translation: t,
                                  },
                                });
                              }}
                            />
                          ))}
                        </div>
                        <div className="triple-fields">
                          {["X", "Y", "Z"].map((axis, i) => (
                            <NumberField
                              key={axis}
                              label={`${axis} rotation`}
                              value={draft.transform.rotation[i]}
                              unit="°"
                              onChange={(n) => {
                                if (n === null) return;
                                setAutomaticAlignment(false);
                                const r = [...draft.transform.rotation];
                                r[i] = n;
                                setDraft({
                                  ...draft,
                                  transform: {
                                    ...draft.transform,
                                    rotation: r,
                                  },
                                });
                              }}
                            />
                          ))}
                        </div>
                        <NumberField
                          label="Uniform scale"
                          value={draft.transform.scale}
                          onChange={(n) => {
                            if (n === null) return;
                            setAutomaticAlignment(false);
                            setDraft({
                              ...draft,
                              transform: { ...draft.transform, scale: n },
                            });
                          }}
                          min={0.000001}
                        />
                        <FieldSelect
                          label="Analysis geometry"
                          value={draft.geometry_mode}
                          onChange={(s) =>
                            setDraft({
                              ...draft,
                              geometry_mode: s as "original" | "replacement",
                            })
                          }
                        >
                          <option value="original">
                            Original OpenRocket geometry
                          </option>
                          <option value="replacement">
                            Detailed imported geometry
                          </option>
                        </FieldSelect>
                        <button
                          className="primary wide"
                          disabled={
                            !assetId ||
                            busy ||
                            (automaticAlignment &&
                              (alignmentPending || !alignmentProposal))
                          }
                          onClick={() =>
                            operation(async () => {
                              assertValidNumberFields();
                              await settings.flush();
                              await acceptProject(
                                await post<Project>("/geometry/attach", {
                                  component_id: draft.id,
                                  asset_id: assetId,
                                  transform: draft.transform,
                                  auto_align: automaticAlignment,
                                  alignment_options: alignmentOptions,
                                  geometry_mode: "replacement",
                                }),
                              );
                              clearResults();
                              setAlignmentProposal(null);
                              setAutomaticAlignment(false);
                              setNotice(
                                "Detailed geometry attached. Inspect alignment and rerun analyses.",
                              );
                            })
                          }
                        >
                          <Link2 size={14} /> Attach & use detailed geometry
                        </button>
                        <button
                          className="secondary wide"
                          disabled={busy}
                          onClick={applyComponent}
                        >
                          Apply alignment / mode
                        </button>
                        <button
                          className="quiet-btn wide"
                          onClick={() => {
                            setOverlays((o) => ({ ...o, original: true }));
                            setWorkspace("studies");
                            setStudyMode("comparison");
                            runCompare();
                          }}
                        >
                          <GitCompareArrows size={14} /> Compare original &
                          detailed
                        </button>
                      </>
                    )}
                    <button
                      className="secondary wide"
                      onClick={() => polarInput.current?.click()}
                      disabled={busy}
                    >
                      <Upload size={14} /> Import aerodynamic polar .csv
                    </button>
                    <p className="microcopy">
                      User-supplied table: mach, cd, cna, cp_m. SI units; exact
                      geometry and configuration binding. You are responsible
                      for validating coefficient data.
                    </p>
                    <div className="engineering-note">
                      <AlertTriangle size={15} />
                      <p>
                        Empirical aerodynamic equations do not resolve arbitrary
                        CAD surface geometry. CP and drag remain scoped
                        estimates. The experimental CFD solver resolves the
                        exposed outer shape without changing material geometry,
                        mass, neighboring parts or FEA. Sealed cavities and
                        enclosed internals add no pressure faces; open bores can
                        admit exterior flow. Inspect small openings and fins at
                        the chosen grid resolution.
                      </p>
                    </div>
                  </div>
                )}
                {designTab === "configuration" && (
                  <div className="inspector-body">
                    <div className="selected-heading">
                      <span className="part-icon">
                        <Rocket size={19} />
                      </span>
                      <div>
                        <h3>{configurationDraft?.name || "Flight setup"}</h3>
                        <span>MOTOR & RECOVERY</span>
                      </div>
                    </div>
                    <FieldSelect
                      label="Motor curve"
                      value={configurationDraft?.motor_id || ""}
                      onChange={(v) => changeConfig("motor_id", v || null)}
                    >
                      <option value="">No motor assigned</option>
                      {project?.motors.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </FieldSelect>
                    <button
                      className="secondary wide"
                      onClick={() => motorInput.current?.click()}
                      disabled={busy}
                    >
                      <Upload size={14} /> Import .eng / .rse motor
                    </button>
                    <button
                      className="secondary wide"
                      disabled={busy || activeJob || !project}
                      onClick={() =>
                        project && setMotorSearchProject(project.id)
                      }
                    >
                      <Globe size={15} /> Find motor online
                    </button>
                    {configurationDraft?.motor_id && (
                      <>
                        <p className="microcopy">
                          {
                            project?.motors.find(
                              (m) => m.id === configurationDraft.motor_id,
                            )?.source
                          }
                        </p>
                        <Chart
                          data={(
                            project?.motors.find(
                              (m) => m.id === configurationDraft.motor_id,
                            )?.curve || []
                          ).map(([time, thrust]) => ({ time, thrust }))}
                          series={[
                            {
                              key: "thrust",
                              label: "Thrust · N",
                              color: "#ddb174",
                            },
                          ]}
                          height={110}
                        />
                      </>
                    )}
                    <div className="panel-divider" />
                    <Toggle
                      label="Recovery settings confirmed"
                      value={configurationDraft?.recovery_defined ?? false}
                      onChange={() =>
                        changeConfig(
                          "recovery_defined",
                          !configurationDraft?.recovery_defined,
                        )
                      }
                    />
                    {configurationDraft?.recovery_defined === false && (
                      <p className="field-error">
                        Flight simulation is unavailable until you enter and
                        confirm the actual chute and deployment settings below.
                      </p>
                    )}
                    <FieldSelect
                      label="Deployment mode"
                      value={configurationDraft?.deployment || "dual"}
                      onChange={(v) => changeConfig("deployment", v)}
                    >
                      <option value="single">Single deployment</option>
                      <option value="dual">Dual deployment</option>
                    </FieldSelect>
                    <SIField
                      label="Main chute effective Cd × area"
                      kind="area"
                      units={units}
                      value={configurationDraft?.main_cd_area ?? null}
                      min={0.000001}
                      onChange={(n) =>
                        n !== null && changeConfig("main_cd_area", n)
                      }
                    />
                    {configurationDraft?.deployment === "dual" && (
                      <>
                        <SIField
                          label="Drogue effective Cd × area"
                          kind="area"
                          units={units}
                          value={configurationDraft?.drogue_cd_area ?? null}
                          min={0.000001}
                          onChange={(n) =>
                            n !== null && changeConfig("drogue_cd_area", n)
                          }
                        />
                        <SIField
                          label="Main deployment altitude AGL"
                          kind="length"
                          units={units}
                          value={
                            configurationDraft?.main_deploy_altitude ?? null
                          }
                          onChange={(n) =>
                            n !== null &&
                            changeConfig("main_deploy_altitude", n)
                          }
                          min={0}
                        />
                      </>
                    )}
                    <FieldSelect
                      label="Primary deployment event"
                      value={
                        configurationDraft?.primary_deploy_event || "apogee"
                      }
                      onChange={(v) => changeConfig("primary_deploy_event", v)}
                    >
                      <option value="apogee">Apogee detection</option>
                      <option value="motor_ejection">
                        Motor ejection after burnout
                      </option>
                    </FieldSelect>
                    {configurationDraft?.primary_deploy_event ===
                      "motor_ejection" && (
                      <NumberField
                        label="Motor ejection delay after burnout"
                        value={configurationDraft.motor_ejection_delay}
                        onChange={(n) =>
                          changeConfig("motor_ejection_delay", n)
                        }
                        unit="s"
                        min={0}
                        hint="Required for motor-ejection deployment; seconds after burnout."
                      />
                    )}
                    <NumberField
                      label="Apogee deployment delay"
                      value={configurationDraft?.apogee_delay ?? null}
                      unit="s"
                      min={0}
                      onChange={(n) =>
                        n !== null && changeConfig("apogee_delay", n)
                      }
                    />
                    <NumberField
                      label="Ignition delay"
                      value={configurationDraft?.ignition_delay ?? null}
                      unit="s"
                      min={0}
                      onChange={(n) =>
                        n !== null && changeConfig("ignition_delay", n)
                      }
                    />
                    <FieldSelect
                      label="Motor mount"
                      value={configurationDraft?.motor_mount_id || ""}
                      onChange={(v) =>
                        changeConfig("motor_mount_id", v || null)
                      }
                    >
                      <option value="">Automatic tail placement</option>
                      {project?.components.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </FieldSelect>
                    <SIField
                      label="Motor position override"
                      kind="length"
                      units={units}
                      value={configurationDraft?.motor_position ?? null}
                      onChange={(n) => changeConfig("motor_position", n)}
                    />
                    <button
                      className="primary wide"
                      disabled={busy || !configurationDraft}
                      onClick={() =>
                        project &&
                        configurationDraft &&
                        operation(async () => {
                          assertValidNumberFields();
                          await saveProject({
                            ...project,
                            configurations: project.configurations.map((c) =>
                              c.id === configurationDraft.id
                                ? configurationDraft
                                : c,
                            ),
                          });
                          setNotice("Flight configuration saved.");
                        })
                      }
                    >
                      <Check size={14} /> Apply flight setup
                    </button>
                    <div className="engineering-note">
                      <Info size={15} />
                      <p>
                        Recovery uses effective drag areas and event-based
                        deployment. Verify chute data and deployment altitudes
                        for your configuration.
                      </p>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="inspector-body">
                  <div className="subheading">
                    <Wind size={13} /> ENVIRONMENT & FLOW
                  </div>
                  {conditionFields}
                  {workspace === "flight" && (
                    <>
                      <div className="panel-divider" />
                      <div className="subheading">
                        <Rocket size={13} /> LAUNCH CONDITIONS
                      </div>
                      <SIField
                        label="Launch rail length"
                        kind="length"
                        units={units}
                        value={conditions.rail_length}
                        onChange={(n) => setCondition("rail_length", n)}
                        min={0.01}
                      />
                      <div className="field-pair">
                        <NumberField
                          label="Angle from vertical"
                          value={conditions.launch_angle}
                          onChange={(n) => setCondition("launch_angle", n)}
                          unit="°"
                          min={0}
                          max={30}
                        />
                        <NumberField
                          label="Launch azimuth"
                          value={conditions.launch_azimuth}
                          onChange={(n) => setCondition("launch_azimuth", n)}
                          unit="°"
                          min={0}
                          max={360}
                        />
                      </div>
                      <div className="field-pair">
                        <NumberField
                          label="Time step"
                          value={conditions.dt}
                          onChange={(n) => setCondition("dt", n)}
                          unit="s"
                          min={0.001}
                          max={0.2}
                        />
                        <NumberField
                          label="Duration limit"
                          value={conditions.max_time}
                          onChange={(n) => setCondition("max_time", n)}
                          unit="s"
                          min={0.001}
                          max={1200}
                        />
                      </div>
                      <NumberField
                        label="Random seed"
                        value={conditions.seed}
                        onChange={(n) => setCondition("seed", n)}
                        step={1}
                        min={0}
                      />
                      <div className="configuration-card">
                        <Rocket size={15} />
                        <div>
                          <strong>{configuration?.name}</strong>
                          <span>
                            {project?.motors.find(
                              (m) => m.id === configuration?.motor_id,
                            )?.name || "No motor assigned"}{" "}
                            · {configuration?.deployment} deployment
                          </span>
                        </div>
                        <button
                          title="Edit flight configuration"
                          onClick={() => {
                            setWorkspace("design");
                            setDesignTab("configuration");
                          }}
                        >
                          <Settings2 size={13} />
                        </button>
                      </div>
                    </>
                  )}
                  {workspace === "structure" && (
                    <>
                      <div className="panel-divider" />
                      <div className="subheading">
                        <Layers size={13} /> FINITE ELEMENT SETUP
                      </div>
                      <p className="panel-intro">
                        Selected:{" "}
                        <strong>
                          {selected?.name || "select a component"}
                        </strong>
                      </p>
                      <Toggle
                        label="Automatic mesh sizing"
                        value={feaOptions.auto_mesh}
                        onChange={() =>
                          setFeaOptions({
                            ...feaOptions,
                            auto_mesh: !feaOptions.auto_mesh,
                          })
                        }
                      />
                      <div className="field-pair">
                        <SIField
                          label="Target mesh size"
                          kind="length"
                          units={units}
                          value={feaOptions.mesh_size}
                          onChange={(n) =>
                            n !== null &&
                            setFeaOptions({
                              ...feaOptions,
                              mesh_size: n,
                              auto_mesh: false,
                            })
                          }
                        />
                        <NumberField
                          label="Element limit"
                          value={feaOptions.max_elements}
                          onChange={(n) =>
                            n !== null &&
                            setFeaOptions({ ...feaOptions, max_elements: n })
                          }
                          step={1000}
                          min={500}
                          max={300000}
                        />
                      </div>
                      <div
                        className="solver-readiness"
                        aria-label="Mesh readiness"
                      >
                        <h4>
                          Mesh readiness{" "}
                          <HelpTip
                            term="Mesh readiness"
                            definition="Checks the actual selected solid, material, known wall thickness, mesh size, and element-budget screen before volume meshing. Passing this check does not validate support conditions, loads, mesh convergence, or CAD wall thickness."
                          />
                        </h4>
                        {feaPreflightPending && (
                          <p role="status">
                            Checking actual component geometry…
                          </p>
                        )}
                        {feaPreflightError && (
                          <p role="alert" className="danger-text">
                            {feaPreflightError}
                          </p>
                        )}
                        {feaPreflight && (
                          <>
                            <p>
                              {feaPreflight.can_run
                                ? "Ready for volume meshing; review loads and supports."
                                : "Resolve the setup below before solid FEA."}
                            </p>
                            {feaPreflight.recommended_mesh_size_m != null && (
                              <p>
                                Suggested mesh:{" "}
                                <strong>
                                  {quantity(
                                    feaPreflight.recommended_mesh_size_m,
                                    "length",
                                    units,
                                  )}
                                </strong>{" "}
                                · estimated{" "}
                                {fmt(
                                  feaPreflight.recommended_estimated_elements,
                                  0,
                                )}{" "}
                                elements. Actual count can be higher.
                              </p>
                            )}
                            {feaPreflight.cad_thickness_unknown && (
                              <p className="warning-text">
                                CAD wall thickness is unknown. Measure thin
                                features and demonstrate mesh convergence;
                                automatic sizing cannot guarantee bending
                                resolution.
                              </p>
                            )}
                            {feaPreflight.errors?.map(
                              (message: string, i: number) => (
                                <p key={i} className="danger-text">
                                  {message}
                                </p>
                              ),
                            )}
                            <button
                              className="secondary wide"
                              disabled={
                                !feaPreflight.recommended_within_maximum_budget ||
                                busy ||
                                activeJob
                              }
                              onClick={() =>
                                setFeaOptions({
                                  ...feaOptions,
                                  auto_mesh: true,
                                  mesh_size:
                                    feaPreflight.recommended_mesh_size_m,
                                  max_elements:
                                    feaPreflight.recommended_max_elements,
                                })
                              }
                            >
                              <Check size={14} /> Use recommended mesh
                            </button>
                            {feaPreflight.recommended_max_elements != null && (
                              <p className="microcopy">
                                This applies the suggested size and an element
                                limit of{" "}
                                {fmt(feaPreflight.recommended_max_elements, 0)}.
                                It may increase the current budget.
                              </p>
                            )}
                            {feaPreflight.geometry_valid &&
                              feaPreflight.recommended_mesh_size_m != null &&
                              !feaPreflight.recommended_within_maximum_budget && (
                                <p>
                                  A thickness-resolving whole-part solid mesh
                                  exceeds the supported budget. Prepare a
                                  smaller physical CAD part externally or use
                                  supported engineering estimates.
                                </p>
                              )}
                            <button
                              className="secondary wide"
                              disabled={
                                !feaPreflight.beam_estimate_available || !canRun
                              }
                              onClick={runAnalysis}
                            >
                              <Gauge size={14} /> Use beam/fin estimates
                            </button>
                          </>
                        )}
                      </div>
                      <FieldSelect
                        label="Clamp type"
                        value={feaOptions.clamp_type}
                        onChange={(s) =>
                          setFeaOptions({ ...feaOptions, clamp_type: s })
                        }
                      >
                        <option value="plane">Coordinate plane</option>
                        <option
                          value="radial_root"
                          disabled={
                            selected?.geometry_mode === "replacement" ||
                            ![
                              "fin",
                              "finset",
                              "trapezoidfinset",
                              "freeformfinset",
                              "ellipticalfinset",
                            ].includes(selected?.kind || "")
                          }
                        >
                          Fin radial root · original fins
                        </option>
                      </FieldSelect>
                      <div className="field-pair">
                        <FieldSelect
                          label="Clamp axis"
                          value={feaOptions.clamp_axis}
                          onChange={(s) =>
                            setFeaOptions({ ...feaOptions, clamp_axis: s })
                          }
                        >
                          {["x", "y", "z"].map((a) => (
                            <option key={a}>{a}</option>
                          ))}
                        </FieldSelect>
                        <FieldSelect
                          label="Clamp side"
                          value={feaOptions.clamp_side}
                          onChange={(s) =>
                            setFeaOptions({ ...feaOptions, clamp_side: s })
                          }
                        >
                          <option value="min">Minimum coordinate</option>
                          <option value="max">Maximum coordinate</option>
                        </FieldSelect>
                      </div>
                      <FieldSelect
                        label="Surface load"
                        value={feaOptions.load_mode}
                        onChange={(s) =>
                          setFeaOptions({ ...feaOptions, load_mode: s })
                        }
                      >
                        <option value="aero_pressure">
                          Estimated aerodynamic pressure
                        </option>
                        <option value="uniform_pressure">
                          Uniform pressure
                        </option>
                        <option value="traction">
                          Prescribed free-end traction
                        </option>
                        <option
                          value="cfd_pressure"
                          disabled={
                            !cfd?.summary?.converged ||
                            cfd?.job_status === "cancelled"
                          }
                        >
                          Converged CFD surface pressure
                        </option>
                      </FieldSelect>
                      {feaOptions.load_mode === "cfd_pressure" &&
                        (!cfd?.summary?.converged ||
                          cfd?.job_status === "cancelled") && (
                          <p className="field-error">
                            Rerun and converge the source CFD job in this
                            session before transferring its pressure. A saved
                            setup does not include numerical result fields.
                          </p>
                        )}
                      {feaOptions.load_mode === "uniform_pressure" && (
                        <SIField
                          label="Applied pressure"
                          kind="pressure"
                          units={units}
                          value={feaOptions.load_pressure_pa}
                          onChange={(n) =>
                            n !== null &&
                            setFeaOptions({
                              ...feaOptions,
                              load_pressure_pa: n,
                            })
                          }
                        />
                      )}
                      {feaOptions.load_mode === "traction" && (
                        <div className="triple-fields">
                          {["X", "Y", "Z"].map((axis, i) => (
                            <SIField
                              key={axis}
                              label={`${axis} end traction`}
                              kind="pressure"
                              units={units}
                              value={feaOptions.traction_pa[i]}
                              onChange={(n) => {
                                if (n === null) return;
                                const values = [...feaOptions.traction_pa];
                                values[i] = n;
                                setFeaOptions({
                                  ...feaOptions,
                                  traction_pa: values,
                                });
                              }}
                            />
                          ))}
                        </div>
                      )}
                      <div className="subheading">
                        PRESCRIBED BODY ACCELERATION
                      </div>
                      <div className="triple-fields">
                        {["X", "Y", "Z"].map((axis, i) => (
                          <SIField
                            key={axis}
                            label={`${axis} body acceleration`}
                            kind="acceleration"
                            units={units}
                            value={feaOptions.acceleration_m_s2[i]}
                            onChange={(n) => {
                              if (n === null) return;
                              const values = [...feaOptions.acceleration_m_s2];
                              values[i] = n;
                              setFeaOptions({
                                ...feaOptions,
                                acceleration_m_s2: values,
                              });
                            }}
                          />
                        ))}
                      </div>
                      <NumberField
                        label="Deformation display scale"
                        value={deformationScale}
                        onChange={(n) => n !== null && setDeformationScale(n)}
                        unit="×"
                        min={0}
                      />
                      <FieldSelect
                        label="Linear solver backend"
                        value={feaOptions.backend}
                        onChange={(s) =>
                          setFeaOptions({ ...feaOptions, backend: s })
                        }
                      >
                        <option value="auto">Auto · GPU if supported</option>
                        <option value="cpu">CPU · SciPy</option>
                        <option value="cuda">CUDA · CuPy</option>
                      </FieldSelect>
                      <div className="engineering-note">
                        <Info size={15} />
                        <p>
                          CFD pressure transfer is one-way and quasi-static,
                          using nearest surface samples; no fluid-structure
                          coupling. Linear static solid FEA. Use mesh size at
                          most half the wall thickness for thin parts. For
                          original fin sets, select Fin radial root. Root faces
                          are fully clamped. Isotropic material assumptions and
                          mesh convergence must be reviewed. Exaggerated
                          deformation is a display aid.
                        </p>
                      </div>
                    </>
                  )}
                  {workspace === "cfd" && (
                    <>
                      <div className="panel-divider" />
                      <div className="subheading">
                        <Activity size={13} /> CARTESIAN EULER SOLVER
                      </div>
                      <Toggle
                        label="Run until converged"
                        value={cfdOptions.run_until_converged}
                        onChange={() =>
                          setCfdOptions({
                            ...cfdOptions,
                            run_until_converged:
                              !cfdOptions.run_until_converged,
                          })
                        }
                      />
                      <p className="microcopy">
                        Convergence mode ignores step and flow-time ceilings.
                        Wall time still applies unless set to 0. Cancel retains
                        actual partial CFD fields. Convergence does not
                        establish accuracy.
                      </p>
                      <div className="field-pair">
                        <NumberField
                          label="Lengthwise grid cells"
                          value={cfdOptions.grid_resolution}
                          onChange={(n) =>
                            n !== null &&
                            setCfdOptions({ ...cfdOptions, grid_resolution: n })
                          }
                          step={4}
                        />
                        <NumberField
                          label="Maximum steps"
                          disabled={cfdOptions.run_until_converged}
                          value={cfdOptions.max_steps}
                          onChange={(n) =>
                            n !== null &&
                            setCfdOptions({ ...cfdOptions, max_steps: n })
                          }
                          step={100}
                        />
                      </div>
                      <div className="field-pair">
                        <NumberField
                          label="Transverse grid cells"
                          value={cfdOptions.transverse_resolution}
                          min={12}
                          max={128}
                          step={4}
                          onChange={(n) =>
                            n !== null &&
                            setCfdOptions({
                              ...cfdOptions,
                              transverse_resolution: n,
                            })
                          }
                        />
                        <NumberField
                          label="Cell budget"
                          value={cfdOptions.max_cells}
                          min={1000}
                          max={2000000}
                          step={10000}
                          onChange={(n) =>
                            n !== null &&
                            setCfdOptions({
                              ...cfdOptions,
                              max_cells: n,
                            })
                          }
                        />
                      </div>
                      <div className="field-pair">
                        <NumberField
                          label="CFL number"
                          value={cfdOptions.cfl}
                          min={0.01}
                          max={0.8}
                          onChange={(n) =>
                            n !== null &&
                            setCfdOptions({ ...cfdOptions, cfl: n })
                          }
                        />
                        <NumberField
                          label="Convergence tolerance"
                          value={cfdOptions.convergence_tolerance}
                          min={0.0000000001}
                          max={0.01}
                          onChange={(n) =>
                            n !== null &&
                            setCfdOptions({
                              ...cfdOptions,
                              convergence_tolerance: n,
                            })
                          }
                        />
                      </div>
                      <NumberField
                        label="Farfield padding"
                        value={cfdOptions.domain_padding}
                        onChange={(n) =>
                          n !== null &&
                          setCfdOptions({ ...cfdOptions, domain_padding: n })
                        }
                        unit="× extent"
                        min={0.15}
                        max={3}
                        hint="Padding on each side as a multiple of that axis's geometry extent. Nose-side padding is at least 0.35; tail-side padding is at least 0.65. Larger domains may require a larger cell budget."
                      />
                      <NumberField
                        label="Flow-through times"
                        disabled={cfdOptions.run_until_converged}
                        value={cfdOptions.flow_through_times}
                        onChange={(n) =>
                          n !== null &&
                          setCfdOptions({
                            ...cfdOptions,
                            flow_through_times: n,
                          })
                        }
                        min={0.1}
                      />
                      <NumberField
                        label="Wall time limit"
                        value={cfdOptions.max_wall_seconds}
                        onChange={(n) =>
                          n !== null &&
                          setCfdOptions({ ...cfdOptions, max_wall_seconds: n })
                        }
                        unit="s"
                        min={0}
                        max={86400}
                        hint="Computer time budget, separate from simulated flow time. 0 disables this limit. With Run until converged enabled and 0 here, the job continues until numerical convergence or cancellation; completion time is unknown."
                      />
                      <FieldSelect
                        label="Compute backend"
                        value={cfdOptions.backend}
                        onChange={(s) =>
                          setCfdOptions({ ...cfdOptions, backend: s })
                        }
                      >
                        <option value="auto">Auto · CUDA if available</option>
                        <option value="cpu">CPU · NumPy</option>
                        <option value="gpu">GPU · NVIDIA CUDA</option>
                      </FieldSelect>
                      <button
                        className="secondary wide"
                        onClick={() => setGpuDiagnosticsOpen(true)}
                      >
                        <Gauge size={14} /> GPU diagnostics
                      </button>
                      <div className="engineering-note">
                        <AlertTriangle size={15} />
                        <p>
                          Experimental inviscid compressible Euler: pressure
                          forces only. No boundary layers, viscous friction,
                          turbulence closure, or validated transonic drag. Check
                          residuals and grid refinement before interpreting a
                          solution.
                        </p>
                      </div>
                      <p className="microcopy">
                        Exterior-connected air only. Sealed cavities and
                        internal parts are excluded from pressure loading. The
                        aerodynamic flow mask does not modify CAD material, mass
                        or FEA geometry.
                      </p>
                    </>
                  )}
                  {workspace === "studies" && (
                    <>
                      <div className="panel-divider" />
                      <div className="subheading">
                        <FlaskConical size={13} />{" "}
                        {studyMode === "comparison"
                          ? "GEOMETRY COMPARISON"
                          : "STUDY SETTINGS"}
                      </div>
                      {studyMode === "comparison" ? (
                        <>
                          <p className="panel-intro">
                            Compare stock geometry against the current attached
                            CAD and all imported flight configurations.
                          </p>
                          <button
                            className="secondary wide"
                            onClick={runCompare}
                            disabled={!canRun}
                          >
                            <GitCompareArrows size={14} /> Fast engineering
                            comparison
                          </button>
                          <button
                            className="secondary wide"
                            onClick={() =>
                              startJob("comparison", { use_flight: true })
                            }
                            disabled={!canRun}
                          >
                            <Orbit size={14} /> Compare flight performance
                          </button>
                          <button
                            className="secondary wide"
                            onClick={() =>
                              startJob("comparison", {
                                ...cfdOptions,
                                use_cfd: true,
                              })
                            }
                            disabled={!canRun}
                          >
                            <Activity size={14} /> Compare with Euler CFD
                          </button>
                          <p className="microcopy">
                            CFD comparison runs two full local solutions using
                            the current grid settings. Empirical CP values
                            remain subject to model limitations.
                          </p>
                        </>
                      ) : (
                        <>
                          <FieldSelect
                            label="Varied parameter"
                            value={studyOptions.parameter}
                            onChange={(s) =>
                              setStudyOptions({ ...studyOptions, parameter: s })
                            }
                          >
                            {[
                              "speed",
                              "mach",
                              "altitude",
                              "angle_of_attack",
                              "wind_speed",
                              "wind_direction",
                              "turbulence",
                              "temperature_delta",
                              "rail_length",
                              "launch_angle",
                              "launch_azimuth",
                            ].map((p) => (
                              <option
                                key={p}
                                value={p}
                                disabled={
                                  studyOptions.flight
                                    ? ["speed", "mach"].includes(p)
                                    : [
                                        "rail_length",
                                        "launch_angle",
                                        "launch_azimuth",
                                      ].includes(p)
                                }
                              >
                                {p === "angle_of_attack" && studyOptions.flight
                                  ? "angle of attack · stress reference"
                                  : p.replaceAll("_", " ")}
                              </option>
                            ))}
                          </FieldSelect>
                          <p className="microcopy">
                            Study ranges use SI values: m/s, m, degrees, and
                            turbulence fraction (0–1).
                          </p>
                          <div className="field-pair">
                            {studyMode === "sweep" ? (
                              <>
                                <NumberField
                                  label="Range start"
                                  value={studyOptions.start}
                                  onChange={(n) =>
                                    n !== null &&
                                    setStudyOptions({
                                      ...studyOptions,
                                      start: n,
                                    })
                                  }
                                />
                                <NumberField
                                  label="Range end"
                                  value={studyOptions.stop}
                                  onChange={(n) =>
                                    n !== null &&
                                    setStudyOptions({
                                      ...studyOptions,
                                      stop: n,
                                    })
                                  }
                                />
                              </>
                            ) : (
                              <>
                                <NumberField
                                  label="Normal mean"
                                  value={studyOptions.mean}
                                  onChange={(n) =>
                                    n !== null &&
                                    setStudyOptions({
                                      ...studyOptions,
                                      mean: n,
                                    })
                                  }
                                />
                                <NumberField
                                  label="Standard deviation"
                                  value={studyOptions.std}
                                  onChange={(n) =>
                                    n !== null &&
                                    setStudyOptions({ ...studyOptions, std: n })
                                  }
                                  min={0}
                                />
                              </>
                            )}
                          </div>
                          <div className="field-pair">
                            <NumberField
                              label="Samples"
                              value={studyOptions.count}
                              onChange={(n) =>
                                n !== null &&
                                setStudyOptions({ ...studyOptions, count: n })
                              }
                              min={2}
                              max={200}
                              step={1}
                            />
                            <NumberField
                              label="Random seed"
                              value={studyOptions.seed}
                              onChange={(n) =>
                                n !== null &&
                                setStudyOptions({ ...studyOptions, seed: n })
                              }
                              step={1}
                              min={0}
                            />
                          </div>
                          <Toggle
                            label="Run complete flight for every sample"
                            value={studyOptions.flight}
                            onChange={() =>
                              setStudyOptions({
                                ...studyOptions,
                                flight: !studyOptions.flight,
                              })
                            }
                          />
                          {((studyOptions.flight &&
                            ["speed", "mach"].includes(
                              studyOptions.parameter,
                            )) ||
                            (!studyOptions.flight &&
                              [
                                "rail_length",
                                "launch_angle",
                                "launch_azimuth",
                              ].includes(studyOptions.parameter))) && (
                            <p className="field-error">
                              Select a parameter used by this solver. Launch
                              speed and Mach are calculated during flight;
                              launch rail and angles apply to flight studies.
                            </p>
                          )}
                          {studyOptions.flight &&
                            studyOptions.parameter === "angle_of_attack" && (
                              <p className="microcopy">
                                This varies only the fixed structural-load
                                reference angle. The point-mass trajectory does
                                not integrate attitude or angle of attack.
                              </p>
                            )}
                          <div className="engineering-note">
                            <Info size={15} />
                            <p>
                              {studyMode === "monte_carlo"
                                ? "Normally distributed samples are seeded and reproducible. Out-of-range inputs are reported and excluded from statistics."
                                : "Each point uses the same conditions and selected solver. Check numerical sensitivity and physical validity across the range."}
                            </p>
                          </div>
                        </>
                      )}
                    </>
                  )}
                </div>
                <div className="inspector-footer">
                  <div className="run-note">
                    <span className="live-dot" />
                    {activeJob
                      ? "Local simulation running"
                      : busy
                        ? "Working…"
                        : "Ready for local analysis"}
                  </div>
                  {workspace === "aero" && (
                    <button
                      className="primary wide run-button"
                      onClick={runAnalysis}
                      disabled={!canRun}
                    >
                      <Play size={15} /> Run aerodynamic analysis
                    </button>
                  )}
                  {workspace === "flight" && (
                    <div className="launch-setup-actions">
                      <button
                        className="secondary wide"
                        onClick={() => {
                          setWorkspace("design");
                          setDesignTab("configuration");
                          setLayout((current) => ({
                            ...current,
                            focus: false,
                            setup: true,
                          }));
                        }}
                      >
                        <Settings2 size={15} /> Motor & recovery setup
                      </button>
                      <button
                        className="secondary wide"
                        disabled={!project || busy || activeJob}
                        onClick={() =>
                          project && setMotorSearchProject(project.id)
                        }
                      >
                        <Globe size={15} /> Find motor online
                      </button>
                      <p className="microcopy">
                        Use the red Launch button above the 3D view.
                        Calculations finish before automatic flight playback
                        begins.
                      </p>
                    </div>
                  )}
                  {workspace === "structure" && (
                    <button
                      className="primary wide run-button"
                      onClick={() =>
                        startJob("fea", {
                          ...feaOptions,
                          component_id: selectedId,
                          cfd_job_id:
                            feaOptions.load_mode === "cfd_pressure"
                              ? resultJobs.cfd
                              : undefined,
                        })
                      }
                      disabled={
                        !canRun ||
                        !selectedId ||
                        feaPreflightPending ||
                        !feaPreflight?.can_run ||
                        (feaOptions.load_mode === "cfd_pressure" &&
                          (!cfd?.summary?.converged ||
                            cfd?.job_status === "cancelled"))
                      }
                    >
                      <Play size={15} /> Run finite element analysis
                    </button>
                  )}
                  {workspace === "cfd" && (
                    <button
                      className="primary wide run-button"
                      onClick={() => startJob("cfd", cfdOptions)}
                      disabled={!canRun}
                    >
                      <Play size={15} /> Solve flow field
                    </button>
                  )}
                  {workspace === "studies" && studyMode !== "comparison" && (
                    <button
                      className="primary wide run-button"
                      onClick={() => startJob(studyMode, studyOptions)}
                      disabled={
                        !canRun ||
                        (studyOptions.flight
                          ? ["speed", "mach"].includes(studyOptions.parameter)
                          : [
                              "rail_length",
                              "launch_angle",
                              "launch_azimuth",
                            ].includes(studyOptions.parameter))
                      }
                    >
                      <Play size={15} /> Run{" "}
                      {studyMode === "sweep"
                        ? "parameter sweep"
                        : "Monte Carlo study"}
                    </button>
                  )}
                </div>
              </>
            )}
          </fieldset>
        </aside>
      </div>
      <footer className="statusbar">
        <span>
          <span className="live-dot" />{" "}
          {health ? "Engine connected" : "Engine unavailable"}
        </span>
        <span
          className={settings.status === "error" ? "danger-text" : ""}
          role="status"
        >
          {settings.status === "saving"
            ? "Saving analysis setup…"
            : settings.status === "pending"
              ? "Analysis setup changed · saving shortly"
              : settings.status === "error"
                ? "Analysis setup not saved · review error"
                : "Analysis setup saved locally"}
        </span>
        <span>Engineering design tool · Review model assumptions</span>
      </footer>
      {guideOpen && (
        <UserGuide
          onClose={() => setGuideOpen(false)}
          onNavigate={setWorkspace}
        />
      )}
      {tutorialTopic && (
        <Tutorials
          key={tutorialTopic}
          workspace={workspace}
          initialTour={tutorialTopic}
          onClose={() => setTutorialTopic(null)}
          onWorkspace={setWorkspace}
        />
      )}
      {motorSearchProject && (
        <MotorSearch
          projectId={motorSearchProject}
          onClose={() => setMotorSearchProject(null)}
          onImported={async (imported) => {
            await acceptProject(imported);
            clearResults();
            setMotorSearchProject(null);
            setWorkspace("design");
            setDesignTab("configuration");
            setLayout((current) => ({ ...current, focus: false, setup: true }));
            setNotice(
              "Motor curve imported. Select it and click Apply flight setup to assign it.",
            );
          }}
        />
      )}
      {mapExpanded && (
        <WindowDialog
          title="Local flight map"
          onClose={() => setMapExpanded(false)}
        >
          <FlightMap
            projectId={project?.id}
            trajectory={flight?.trajectory || []}
            events={flight?.events || []}
            flightRow={row}
            conditions={flight?.inputs?.conditions || conditions}
            units={units}
            onSeek={(time) => {
              setPlayTime(time);
              setPlaying(false);
            }}
          />
        </WindowDialog>
      )}
      {gpuDiagnosticsOpen && (
        <WindowDialog
          title="GPU diagnostics"
          onClose={() => setGpuDiagnosticsOpen(false)}
        >
          <div className="gpu-diagnostics">
            <p>
              Numerical CUDA acceleration requires an NVIDIA GPU. This checks
              allocation and a real compiled calculation; 3D rendering uses a
              separate graphics path.
            </p>
            <h3>
              {health?.capabilities?.gpu_compute
                ? "CUDA calculation available"
                : "CUDA calculation unavailable"}
            </h3>
            {health?.capabilities?.gpu_diagnostics?.devices?.map(
              (device: any) => (
                <p key={device.index}>
                  <strong>{device.name}</strong> ·{" "}
                  {fmt(device.memory_total_bytes / 1024 ** 3, 1)} GiB · compute
                  capability {device.compute_capability}
                </p>
              ),
            )}
            {health?.capabilities?.gpu_diagnostics && (
              <dl>
                {Object.entries(health.capabilities.gpu_diagnostics)
                  .filter(([key]) => !["available", "devices"].includes(key))
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll("_", " ")}</dt>
                      <dd>
                        {typeof value === "object"
                          ? JSON.stringify(value)
                          : String(value ?? "Unknown")}
                      </dd>
                    </div>
                  ))}
              </dl>
            )}
            <p>
              Automatic backend falls back to CPU and records the reason.
              Explicit GPU selection reports a failure instead. Restart the
              application after changing a driver so diagnostics are checked
              again.
            </p>
          </div>
        </WindowDialog>
      )}
    </div>
  );
}
