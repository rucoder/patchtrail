// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { getPatch } from "../api";
import { useApp } from "../app-context";
import { clampPanel, type ActFn } from "../lib/panel";
import type { Tab } from "../lib/route";
import type { Card, Detail } from "../types";
import { History } from "./History";
import { Overview } from "./Overview";
import { PanelHeader } from "./PanelHeader";
import { Thread } from "./Thread";

type Props = { height: number; onResize: (h: number) => void; onResizeEnd: (h: number) => void };
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function Panel(props: Props) {
  const { route } = useApp();
  return route.name === null ? null : <Open key={route.name} name={route.name} tab={route.tab} {...props} />;
}

function Open({ name, tab, height, onResize, onResizeEnd }: Props & { name: string; tab: Tab }) {
  const { patches, navigate, runAction } = useApp();
  const listCard = patches.find((p) => p.name === name) ?? null;
  const cardJson = JSON.stringify(listCard);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [local, setLocal] = useState<Card | null>(null); // the card an action just returned
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // bumped after each detail load: the thread reloads with it
  const seq = useRef(0);

  const load = useCallback(async () => {
    const s = ++seq.current;
    try {
      const d = await getPatch(name);
      if (s === seq.current) {
        setDetail(d);
        setTick((t) => t + 1);
        setError(null);
      }
    } catch (e) {
      if (s === seq.current) setError(msg(e));
    }
  }, [name]);
  // On open, and whenever this card's JSON changes in the list refresh (not when the list
  // first arrives after a deep link: the open already loaded it).
  const seen = useRef<string | null>(null);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (seen.current !== null && seen.current !== cardJson) void load();
    seen.current = cardJson === "null" ? null : cardJson;
  }, [load, cardJson]);
  useEffect(() => setLocal(null), [cardJson]);

  const close = useCallback(() => navigate({ name: null, tab: "overview" }), [navigate]);
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key === "Escape" && !(t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);

  const act: ActFn = async (action, body = {}) => {
    try {
      const c = await runAction(name, action, body);
      setLocal(c);
      setError(null);
      await load();
      return true;
    } catch (e) {
      setError(msg(e));
      return false;
    }
  };

  const head: Card | null = local ?? listCard ?? detail;
  const hh = useRef(height);
  hh.current = height;
  const drag = (e: MouseEvent) => {
    e.preventDefault();
    const y0 = e.clientY, h0 = height;
    const next = (ev: globalThis.MouseEvent) => clampPanel(h0 + (y0 - ev.clientY), window.innerHeight);
    const move = (ev: globalThis.MouseEvent) => onResize(next(ev));
    const up = (ev: globalThis.MouseEvent) => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      onResizeEnd(next(ev));
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };
  const splitKey = (e: KeyboardEvent) => {
    const d = e.key === "ArrowUp" ? 20 : e.key === "ArrowDown" ? -20 : 0;
    if (!d) return;
    e.preventDefault();
    const h = clampPanel(hh.current + d, window.innerHeight);
    onResize(h);
    onResizeEnd(h);
  };

  const threadN = detail?.thread.length ?? 0;
  const tabs: [Tab, React.ReactNode][] = [
    ["overview", "Overview"],
    ["thread", <>Thread{detail ? ` · ${threadN}` : ""}{detail?.thread.some((m) => m.new) && <> <span className="dot" /></>}</>],
    ["history", "History"],
  ];
  return (
    <>
      <div className="split" role="separator" aria-orientation="horizontal" aria-label="Resize panel" tabIndex={0}
        onMouseDown={drag} onKeyDown={splitKey}><i /></div>
      <div className="panel" style={{ height }}>
        {head ? (
          <PanelHeader card={head} loreUrl={detail?.lore_url ?? null} act={act} onClose={close} />
        ) : (
          <div className="phead"><span className="mono muted">{name}</span><span style={{ flex: 1 }} />
            <button type="button" className="x" aria-label="Close panel" onClick={close}>×</button></div>
        )}
        {error && <div className="perr bad" role="alert">{error}</div>}
        <div className="tabs" role="tablist">
          {tabs.map(([t, label]) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t}
              className={tab === t ? "tab on" : "tab"} onClick={() => navigate({ name, tab: t })}>{label}</button>
          ))}
        </div>
        <div className="pbody">
          {!detail ? (
            !error && <div className="muted">Loading…</div>
          ) : tab === "overview" ? (
            <Overview d={detail} card={head ?? detail} act={act} />
          ) : tab === "history" ? (
            <History d={detail} />
          ) : (
            <Thread name={name} tick={tick} />
          )}
        </div>
      </div>
    </>
  );
}
