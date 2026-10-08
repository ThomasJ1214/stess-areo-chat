import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  Compass,
  ExternalLink,
  RotateCcw,
  X,
} from "lucide-react";
import type { Workspace } from "./types";
import {
  parseTutorialProgress,
  tutorialStorageKey,
  tutorialTours,
  workspaceTitles,
  type TourId,
  type TutorialProgress,
} from "./tutorialData";

function readProgress() {
  try {
    return parseTutorialProgress(localStorage.getItem(tutorialStorageKey));
  } catch {
    return {};
  }
}

/** Offline, resumable instructions. No solver action or project mutation is performed by a tutorial. */
export default function Tutorials({
  workspace,
  onClose,
  onWorkspace,
  initialTour,
}: {
  workspace: Workspace;
  onClose: () => void;
  onWorkspace: (workspace: Workspace) => void;
  initialTour?: TourId;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const stepTitle = useRef<HTMLHeadingElement>(null);
  const [tourId, setTourId] = useState<TourId>(initialTour ?? workspace);
  const [progress, setProgress] =
    useState<Partial<Record<TourId, TutorialProgress>>>(readProgress);
  const tour = tutorialTours.find((item) => item.id === tourId)!;
  const state = progress[tourId] ?? { step: 0, completed: false };
  const step = tour.steps[state.step];
  const percent = state.completed
    ? 100
    : Math.round((state.step / tour.steps.length) * 100);
  useEffect(() => {
    const element = dialog.current!;
    const previousFocus = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
        previousFocus.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(tutorialStorageKey, JSON.stringify(progress));
    } catch {
      // Help remains usable when local storage is unavailable.
    }
  }, [progress]);
  function move(stepIndex: number, completed = false) {
    setProgress((current) => ({
      ...current,
      [tourId]: { step: stepIndex, completed },
    }));
    requestAnimationFrame(() =>
      stepTitle.current?.focus({ preventScroll: true }),
    );
  }
  function go() {
    // Close first so restored focus is not trapped in a page being unmounted.
    onClose();
    onWorkspace(step.workspace);
  }
  return (
    <dialog
      ref={dialog}
      className="tutorial-dialog"
      aria-labelledby="tutorial-dialog-title"
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="tutorial-content">
        <header className="tutorial-header">
          <div>
            <Compass size={22} aria-hidden="true" />
            <h2 id="tutorial-dialog-title">Guided tutorials</h2>
          </div>
          <button
            type="button"
            className="tutorial-close"
            aria-label="Close tutorial"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        <p className="tutorial-intro">
          One step at a time. Open the page and try the instruction. Reopen
          Getting started for the whole-app tour, or Tutorial for the current
          page. Your place in each topic is saved on this computer.
        </p>
        <div className="tutorial-body">
          <nav className="tutorial-list" aria-label="Tutorial topics">
            {tutorialTours.map((item) => (
              <button
                type="button"
                key={item.id}
                className={tourId === item.id ? "active" : ""}
                aria-current={tourId === item.id ? "step" : undefined}
                onClick={() => setTourId(item.id)}
              >
                {progress[item.id]?.completed ? (
                  <CheckCircle2 size={16} aria-hidden="true" />
                ) : (
                  <BookOpen size={16} aria-hidden="true" />
                )}
                <span>{item.title}</span>
                {item.id === workspace && <small>Current page</small>}
              </button>
            ))}
          </nav>
          <section
            className="tutorial-step"
            aria-labelledby="tutorial-step-title"
          >
            <div className="tutorial-progress-label">
              <span>{tour.title}</span>
              <span>
                {state.completed
                  ? "Complete"
                  : `Step ${state.step + 1} of ${tour.steps.length}`}
              </span>
            </div>
            <progress
              className="tutorial-progress"
              value={percent}
              max={100}
              aria-label={`${tour.title} progress`}
            >
              {percent}%
            </progress>
            {state.completed ? (
              <div className="tutorial-complete">
                <CheckCircle2 size={36} aria-hidden="true" />
                <h3 id="tutorial-step-title" ref={stepTitle} tabIndex={-1}>
                  Tutorial complete
                </h3>
                <p>
                  You have reached the end of {tour.title.toLowerCase()}. Reopen
                  any topic for a refresher; completion records that you read
                  the steps, not that a design or solver result is validated.
                </p>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => move(0)}
                >
                  <RotateCcw size={15} /> Start again
                </button>
              </div>
            ) : (
              <>
                <h3 id="tutorial-step-title" ref={stepTitle} tabIndex={-1}>
                  {step.title}
                </h3>
                <p className="tutorial-instruction">{step.instruction}</p>
                <div className="tutorial-check">
                  <Check size={18} aria-hidden="true" />
                  <div>
                    <strong>What to check</strong>
                    <p>{step.check}</p>
                  </div>
                </div>
                {step.note && (
                  <p className="tutorial-note">
                    <strong>Model limit or useful detail</strong>
                    {step.note}
                  </p>
                )}
                <button
                  type="button"
                  className="secondary tutorial-open-page"
                  onClick={go}
                >
                  <ExternalLink size={15} /> Open{" "}
                  {workspaceTitles[step.workspace]} & try this step
                </button>
              </>
            )}
          </section>
        </div>
        <footer className="tutorial-footer">
          <button
            type="button"
            className="tutorial-reset"
            onClick={() => move(0)}
          >
            <RotateCcw size={14} /> Restart topic
          </button>
          <div>
            <button
              type="button"
              className="secondary"
              disabled={state.step === 0 && !state.completed}
              onClick={() =>
                move(Math.max(0, state.step - (state.completed ? 0 : 1)))
              }
            >
              <ArrowLeft size={15} /> Previous
            </button>
            {state.completed ? (
              <button type="button" className="primary" onClick={onClose}>
                <Check size={15} /> Done
              </button>
            ) : (
              <button
                type="button"
                className="primary"
                onClick={() =>
                  state.step === tour.steps.length - 1
                    ? move(state.step, true)
                    : move(state.step + 1)
                }
              >
                {state.step === tour.steps.length - 1
                  ? "Finish tutorial"
                  : "Next step"}
                <ArrowRight size={15} />
              </button>
            )}
          </div>
        </footer>
      </div>
    </dialog>
  );
}
