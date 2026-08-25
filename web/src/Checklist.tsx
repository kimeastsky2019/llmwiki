/** 진단 초기 체크리스트 — 현장에 종이로 들고 나가는 한 장.
 *
 * 회의에서 나온 그림 그대로다. 업종을 고르면 과거 진단에서 실제로 나왔던 개선안이
 * **설비별로** 묶여 나오고, 현장 투어를 돌며 해당/비해당을 친다. 그래서 이 화면의
 * 1급 기능은 편집이 아니라 **인쇄**다.
 *
 * 아이템을 지어내지 않는다. 위키에 measure 페이지가 없으면 설비 골격만 나오고
 * 화면이 그 사실을 말한다 — 근거 없는 목록은 현장에서 한 번 쓰이고 버려진다.
 */
import { useCallback, useEffect, useState } from "react";
import { api, type Checklist, type ChecklistGroup, type ChecklistSummary, type KbSector } from "./api";
import { useLang } from "./i18n";

const EMPTY: Checklist = {
  id: "",
  title: "",
  sector: "",
  subsector: "",
  site: "",
  homepage: "",
  owner: "",
  note: "",
  groups: [],
  updated_at: "",
};

export default function ChecklistView() {
  const { t } = useLang();
  const [sectors, setSectors] = useState<KbSector[]>([]);
  const [list, setList] = useState<ChecklistSummary[]>([]);
  const [draft, setDraft] = useState<Checklist | null>(null);
  const [hint, setHint] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    api.audit
      .list()
      .then((r) => setList(r.checklists))
      .catch((e) => setErr((e as Error).message));
  }, []);

  useEffect(() => {
    api.kb.sectors().then((r) => setSectors(r.sectors)).catch(() => setSectors([]));
    reload();
  }, [reload]);

  const startNew = useCallback(
    async (sector: string) => {
      if (!sector) return;
      setBusy(true);
      setErr(null);
      try {
        const d = await api.audit.draft(sector);
        setDraft({
          ...EMPTY,
          sector,
          title: t("clDefaultTitle", { sector: d.sector_name }),
          groups: d.groups,
        });
        setHint(
          d.from_wiki
            ? t("clFromWiki", { n: d.item_count, m: d.wiki_measures })
            : t("clNoWiki")
        );
      } catch (e) {
        setErr((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [t]
  );

  const open = useCallback(async (id: string) => {
    setBusy(true);
    setErr(null);
    try {
      setDraft(await api.audit.get(id));
      setHint("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const save = useCallback(async () => {
    if (!draft) return;
    setBusy(true);
    setErr(null);
    try {
      const saved = await api.audit.save(draft);
      setDraft(saved);
      setHint(t("clSaved"));
      reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [draft, reload, t]);

  const remove = useCallback(
    async (id: string) => {
      if (!window.confirm(t("clConfirmDelete"))) return;
      try {
        await api.audit.remove(id);
        if (draft?.id === id) setDraft(null);
        reload();
      } catch (e) {
        setErr((e as Error).message);
      }
    },
    [draft, reload, t]
  );

  const patch = (p: Partial<Checklist>) => setDraft((d) => (d ? { ...d, ...p } : d));

  const patchItem = (gi: number, ii: number, field: "checked" | "note", value: string) =>
    setDraft((d) => {
      if (!d) return d;
      const groups = d.groups.map((g, i) =>
        i !== gi
          ? g
          : { ...g, items: g.items.map((it, j) => (j !== ii ? it : { ...it, [field]: value })) }
      );
      return { ...d, groups };
    });

  const addItem = (gi: number) =>
    setDraft((d) => {
      if (!d) return d;
      const groups = d.groups.map((g, i) =>
        i !== gi
          ? g
          : {
              ...g,
              items: [
                ...g.items,
                { id: Math.random().toString(36).slice(2, 10), name: "", source: "", checked: "", note: "" },
              ],
            }
      );
      return { ...d, groups };
    });

  const renameItem = (gi: number, ii: number, name: string) =>
    setDraft((d) => {
      if (!d) return d;
      const groups = d.groups.map((g, i) =>
        i !== gi ? g : { ...g, items: g.items.map((it, j) => (j !== ii ? it : { ...it, name })) }
      );
      return { ...d, groups };
    });

  const dropItem = (gi: number, ii: number) =>
    setDraft((d) => {
      if (!d) return d;
      const groups = d.groups.map((g, i) =>
        i !== gi ? g : { ...g, items: g.items.filter((_, j) => j !== ii) }
      );
      return { ...d, groups };
    });

  return (
    <div className="page checklist">
      <h1 className="no-print">{t("clTitle")}</h1>
      <p className="lede no-print">{t("clLede")}</p>

      {err && <div className="banner error no-print">{err}</div>}

      {!draft && (
        <>
          <section className="cl-new no-print">
            <h3>{t("clNewHeading")}</h3>
            <div className="cl-new-row">
              <select defaultValue="" onChange={(e) => startNew(e.target.value)} disabled={busy}>
                <option value="">{t("clPickSector")}</option>
                {sectors.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.name}
                  </option>
                ))}
              </select>
              <span className="muted small">{t("clNewHint")}</span>
            </div>
          </section>

          <section className="no-print">
            <h3>{t("clSavedHeading", { n: list.length })}</h3>
            {!list.length && <p className="muted">{t("clNoneSaved")}</p>}
            <div className="cl-list">
              {list.map((c) => (
                <div key={c.id} className="cl-card">
                  <button className="cl-card-open" onClick={() => open(c.id)}>
                    <strong>{c.title}</strong>
                    <span className="muted small">
                      {c.site || t("clNoSite")} · {c.subsector || c.sector} · {t("clItems", { n: c.item_count })}
                    </span>
                    <span className="muted small">{c.updated_at.slice(0, 10)}</span>
                  </button>
                  <button className="cl-del" onClick={() => remove(c.id)} title={t("clDelete")}>
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </section>
        </>
      )}

      {draft && (
        <>
          <div className="cl-toolbar no-print">
            <button onClick={() => setDraft(null)}>{t("clBack")}</button>
            <div className="spacer" />
            <button className="primary" onClick={save} disabled={busy}>
              {busy ? t("clSaving") : t("clSave")}
            </button>
            <button onClick={() => window.print()}>{t("clPrint")}</button>
          </div>

          {hint && <div className="banner ok no-print">{hint}</div>}

          <div className="cl-sheet">
            <div className="cl-head">
              <input
                className="cl-title-input"
                value={draft.title}
                onChange={(e) => patch({ title: e.target.value })}
                placeholder={t("clTitlePlaceholder")}
              />
              <div className="cl-meta">
                <label>
                  <span>{t("clSite")}</span>
                  <input value={draft.site} onChange={(e) => patch({ site: e.target.value })} />
                </label>
                <label>
                  <span>{t("clSubsector")}</span>
                  <input
                    value={draft.subsector}
                    onChange={(e) => patch({ subsector: e.target.value })}
                    placeholder={t("clSubsectorHint")}
                  />
                </label>
                <label>
                  <span>{t("clHomepage")}</span>
                  <input
                    value={draft.homepage}
                    onChange={(e) => patch({ homepage: e.target.value })}
                    placeholder="https://"
                  />
                </label>
                <label>
                  <span>{t("clOwner")}</span>
                  <input value={draft.owner} onChange={(e) => patch({ owner: e.target.value })} />
                </label>
                <label className="cl-date">
                  <span>{t("clVisitDate")}</span>
                  <input />
                </label>
              </div>
            </div>

            {draft.groups.map((g: ChecklistGroup, gi: number) => (
              <section key={g.equipment} className="cl-group">
                <h3>
                  {g.equipment}
                  <button className="cl-add no-print" onClick={() => addItem(gi)}>
                    + {t("clAddItem")}
                  </button>
                </h3>

                <div className="cl-fields">
                  {g.fields.map((f) => (
                    <span key={f} className="cl-field">
                      {f} <i />
                    </span>
                  ))}
                </div>

                {!g.items.length && <p className="muted small cl-empty">{t("clGroupEmpty")}</p>}

                <table className="cl-table">
                  <thead>
                    <tr>
                      <th className="cl-c">{t("clApplicable")}</th>
                      <th>{t("clItem")}</th>
                      <th className="cl-n">{t("clFieldNote")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.items.map((it, ii) => (
                      <tr key={it.id}>
                        <td className="cl-c">
                          <label className="cl-yn">
                            <input
                              type="radio"
                              name={`${gi}-${ii}`}
                              checked={it.checked === "y"}
                              onChange={() => patchItem(gi, ii, "checked", "y")}
                            />
                            <span>{t("clYes")}</span>
                          </label>
                          <label className="cl-yn">
                            <input
                              type="radio"
                              name={`${gi}-${ii}`}
                              checked={it.checked === "n"}
                              onChange={() => patchItem(gi, ii, "checked", "n")}
                            />
                            <span>{t("clNo")}</span>
                          </label>
                        </td>
                        <td>
                          <input
                            className="cl-item-name"
                            value={it.name}
                            onChange={(e) => renameItem(gi, ii, e.target.value)}
                            placeholder={t("clItemPlaceholder")}
                          />
                          {it.source && <span className="cl-src">{it.source}</span>}
                        </td>
                        <td className="cl-n">
                          <input
                            value={it.note}
                            onChange={(e) => patchItem(gi, ii, "note", e.target.value)}
                          />
                          <button className="cl-del no-print" onClick={() => dropItem(gi, ii)}>
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ))}

            <p className="cl-foot muted small">{t("clFootNote")}</p>
          </div>
        </>
      )}
    </div>
  );
}
