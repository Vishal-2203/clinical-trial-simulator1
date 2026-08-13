import React, { useState, useCallback, useRef } from "react";

const API = "http://localhost:8000";

// ─── Color Palette ────────────────────────────────────────────────────────────
const C = {
  bg: "#0b0f1a",
  surface: "rgba(255,255,255,0.04)",
  surfaceHover: "rgba(255,255,255,0.07)",
  border: "rgba(255,255,255,0.08)",
  accent: "#6c63ff",
  accentGlow: "rgba(108,99,255,0.25)",
  success: "#22d3a0",
  warning: "#f59e0b",
  danger: "#ef4444",
  text: "#e2e8f0",
  muted: "#64748b",
  teal: "#06b6d4",
};

// ─── Efficacy Gauge ───────────────────────────────────────────────────────────
function EfficacyGauge({ value, ciLow, ciHigh }) {
  const pct = Math.round(value);
  const color = pct >= 75 ? C.success : pct >= 50 ? C.warning : pct >= 25 ? "#f97316" : C.danger;
  const r = 70, cx = 90, cy = 90;
  const circumference = 2 * Math.PI * r;
  const arcLength = circumference * 0.75;
  const filledLength = arcLength * (pct / 100);

  return (
    <div style={{ textAlign: "center" }}>
      <svg width="180" height="140" viewBox="0 0 180 140">
        {/* Background arc */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,255,255,0.08)"
          strokeWidth="12" strokeDasharray={`${arcLength} ${circumference}`}
          strokeLinecap="round" style={{ transform: "rotate(135deg)", transformOrigin: `${cx}px ${cy}px` }} />
        {/* Filled arc */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={color}
          strokeWidth="12" strokeDasharray={`${filledLength} ${circumference}`}
          strokeLinecap="round"
          style={{ transform: "rotate(135deg)", transformOrigin: `${cx}px ${cy}px`, transition: "stroke-dasharray 1s ease" }}
          filter={`drop-shadow(0 0 8px ${color}88)`} />
        {/* CI range arc */}
        <text x={cx} y={cy - 10} textAnchor="middle" fill={color} fontSize="28" fontWeight="800">{pct}%</text>
        <text x={cx} y={cy + 14} textAnchor="middle" fill={C.muted} fontSize="10">Efficacy</text>
        <text x={cx} y={cy + 30} textAnchor="middle" fill={C.muted} fontSize="9">
          CI: {ciLow}% – {ciHigh}%
        </text>
      </svg>
    </div>
  );
}

// ─── Toxicity Badge ────────────────────────────────────────────────────────────
function ToxBadge({ cls, probs }) {
  const colors = { None: C.success, Low: C.teal, Moderate: C.warning, Severe: C.danger };
  const color = colors[cls] || C.muted;
  return (
    <div style={{ padding: "16px", background: `${color}18`, border: `1px solid ${color}44`, borderRadius: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <div style={{ width: 10, height: 10, borderRadius: "50%", background: color, boxShadow: `0 0 8px ${color}` }} />
        <span style={{ color, fontWeight: 700, fontSize: 14 }}>{cls} Toxicity Risk</span>
      </div>
      {Object.entries(probs).map(([label, prob]) => (
        <div key={label} style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: C.muted, marginBottom: 2 }}>
            <span>{label}</span><span>{Math.round(prob * 100)}%</span>
          </div>
          <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 4 }}>
            <div style={{ height: "100%", width: `${prob * 100}%`, background: colors[label] || C.muted, borderRadius: 4, transition: "width 1s ease" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── PK Panel ─────────────────────────────────────────────────────────────────
function PKPanel({ pk }) {
  const items = [
    { label: "Bioavailability", value: `${Math.round(pk.bioavailability * 100)}%`, icon: "💊" },
    { label: "Half-life", value: `${pk.half_life_h}h`, icon: "⏱️" },
    { label: "Clearance", value: `${pk.clearance_L_h} L/h`, icon: "🔄" },
    { label: "Volume Dist.", value: `${pk.volume_of_distribution_L} L`, icon: "🫁" },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
      {items.map(it => (
        <div key={it.label} style={{ padding: "12px 14px", background: C.surface, borderRadius: 10, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 18, marginBottom: 4 }}>{it.icon}</div>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.teal }}>{it.value}</div>
          <div style={{ fontSize: 10, color: C.muted }}>{it.label}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Drug Input Row ────────────────────────────────────────────────────────────
function DrugRow({ idx, drug, onChange, onRemove }) {
  const [lookupResult, setLookupResult] = useState(null);
  const [looking, setLooking] = useState(false);

  const handleLookup = async (name) => {
    if (!name || name.length < 3) return;
    setLooking(true);
    try {
      const res = await fetch(`${API}/dti/drug-lookup?name=${encodeURIComponent(name)}`);
      if (res.ok) {
        const data = await res.json();
        setLookupResult(data);
        onChange(idx, { ...drug, resolvedSmiles: data.smiles });
      } else {
        setLookupResult({ error: "Not found in ChEMBL" });
      }
    } catch { setLookupResult({ error: "Lookup failed" }); }
    setLooking(false);
  };

  const isSmiles = drug.input && /[=()\[\]#@/\\]/.test(drug.input);

  return (
    <div style={{ padding: "14px 16px", background: C.surface, borderRadius: 12, border: `1px solid ${C.border}`, marginBottom: 10 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>
            Drug {idx + 1} — Name or SMILES
          </label>
          <input
            value={drug.input}
            onChange={e => onChange(idx, { ...drug, input: e.target.value })}
            onBlur={e => !isSmiles && handleLookup(e.target.value)}
            placeholder='e.g. "Osimertinib" or CC(=O)Nc1ccc(O)cc1'
            style={{
              width: "100%", padding: "9px 12px", background: "rgba(255,255,255,0.06)",
              border: `1px solid ${C.border}`, borderRadius: 8, color: C.text, fontSize: 13,
              outline: "none", boxSizing: "border-box",
            }}
          />
          {lookupResult && !lookupResult.error && (
            <div style={{ fontSize: 10, color: C.success, marginTop: 4 }}>
              ✓ Found: {lookupResult.smiles?.slice(0, 40)}... (MW={lookupResult.properties?.molecular_weight})
            </div>
          )}
          {lookupResult?.error && <div style={{ fontSize: 10, color: C.warning, marginTop: 4 }}>⚠ {lookupResult.error}</div>}
          {looking && <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>Looking up in ChEMBL...</div>}
          {isSmiles && <div style={{ fontSize: 10, color: C.teal, marginTop: 4 }}>✓ Detected as SMILES string</div>}
        </div>
        <div style={{ width: 90 }}>
          <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>Ratio (%)</label>
          <input
            type="number" min="1" max="100"
            value={Math.round(drug.ratio * 100)}
            onChange={e => onChange(idx, { ...drug, ratio: parseInt(e.target.value || 0) / 100 })}
            style={{
              width: "100%", padding: "9px 10px", background: "rgba(255,255,255,0.06)",
              border: `1px solid ${C.border}`, borderRadius: 8, color: C.text, fontSize: 13, boxSizing: "border-box",
            }}
          />
        </div>
        <button onClick={() => onRemove(idx)}
          style={{ marginTop: 18, padding: "8px 10px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, color: C.danger, cursor: "pointer", fontSize: 14 }}>
          ×
        </button>
      </div>
      {drug.resolvedSmiles && (
        <div style={{ marginTop: 8, fontSize: 10, color: C.muted, wordBreak: "break-all" }}>
          SMILES: {drug.resolvedSmiles}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────
export default function NovelPathogenAnalyzer() {
  // Pathogen state
  const [pathogenMode, setPathogenMode] = useState("text"); // "text" | "fasta"
  const [pathogenInput, setPathogenInput] = useState("");

  // Drug state
  const [drugs, setDrugs] = useState([
    { input: "", ratio: 0.5, resolvedSmiles: "" },
    { input: "", ratio: 0.5, resolvedSmiles: "" },
  ]);

  // Patient state
  const [patient, setPatient] = useState({
    age: 45, weight: 72, sex: "male",
    gfr: 90, ast: 25, alt: 25,
    comorbidities: [],
  });

  // Result state
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("efficacy");

  const COMORBIDITIES = ["diabetes", "hypertension", "ckd", "heart_failure", "copd", "liver_disease", "obesity", "cancer"];

  const toggleComorbidity = (c) => {
    setPatient(p => ({
      ...p,
      comorbidities: p.comorbidities.includes(c)
        ? p.comorbidities.filter(x => x !== c)
        : [...p.comorbidities, c],
    }));
  };

  const addDrug = () => {
    const remaining = Math.max(0, 1 - drugs.reduce((s, d) => s + d.ratio, 0));
    setDrugs(d => [...d, { input: "", ratio: remaining, resolvedSmiles: "" }]);
  };

  const updateDrug = (idx, newDrug) => setDrugs(d => d.map((x, i) => i === idx ? newDrug : x));
  const removeDrug = (idx) => setDrugs(d => d.filter((_, i) => i !== idx));

  const EXAMPLE_FASTA = `>Novel_RNA_Virus_NS5_Polymerase
MKTIIALSYIFCLVFADTKIEVEGSSIGNFKAIDLKRPSSMPFNQQTEVHNMTEEEVEEPDLPLKSDKSIYNMRDPQF
GLKSNLRTVIGGKPNIKLAALGDTSGSPILDKCGRVIGLYGNGVVMPDVPEDLNLAAEGFEKQHTVDVLNLKPKEREL`;

  const EXAMPLE_TEXT = "Enveloped RNA virus with glycoprotein spike. NS5 RNA-directed RNA polymerase. Similar to Dengue/Zika family. Positive-sense single-stranded RNA genome. Infects endothelial cells and macrophages.";

  const handleAnalyze = async () => {
    if (!pathogenInput.trim()) { setError("Please enter a pathogen description or FASTA sequence."); return; }
    if (!drugs.some(d => d.input.trim())) { setError("Please enter at least one drug."); return; }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const payload = {
        pathogen_input: pathogenInput.trim(),
        drugs: drugs.filter(d => d.input.trim()).map(d => ({
          input: d.resolvedSmiles || d.input,
          ratio: d.ratio,
        })),
        patient,
      };

      const res = await fetch(`${API}/dti/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Analysis failed");
      }

      const data = await res.json();
      setResult(data);
      setActiveTab("efficacy");
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  };

  // ─── Render ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: "'Inter', sans-serif", padding: "28px 24px" }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <div style={{ width: 44, height: 44, borderRadius: 12, background: `linear-gradient(135deg, ${C.accent}, ${C.teal})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>🧬</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800 }}>Novel Pathogen Drug Analyzer</h1>
            <p style={{ margin: 0, fontSize: 13, color: C.muted }}>Predict drug efficacy against any pathogen — known or completely new — using ESM-2 + ChEMBL 37</p>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {["ESM-2 650M Protein Encoder", "RDKit ECFP4 Drug Encoder", "Patient-Adjusted PK/PD"].map(tag => (
            <span key={tag} style={{ padding: "3px 10px", background: `${C.accent}22`, border: `1px solid ${C.accent}44`, borderRadius: 20, fontSize: 10, color: C.accent }}>{tag}</span>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* ─── LEFT COLUMN: Inputs ─────────────────────────────────────────── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Pathogen Panel */}
          <div style={{ padding: "20px", background: C.surface, borderRadius: 16, border: `1px solid ${C.border}` }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>🦠 Pathogen Input</h3>
              <div style={{ display: "flex", background: "rgba(255,255,255,0.06)", borderRadius: 8, padding: 2 }}>
                {[["text", "📝 Text Description"], ["fasta", "🔬 FASTA Sequence"]].map(([mode, label]) => (
                  <button key={mode} onClick={() => setPathogenMode(mode)}
                    style={{
                      padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: 11, fontWeight: 600,
                      background: pathogenMode === mode ? C.accent : "transparent",
                      color: pathogenMode === mode ? "#fff" : C.muted,
                    }}>{label}</button>
                ))}
              </div>
            </div>

            <textarea
              value={pathogenInput}
              onChange={e => setPathogenInput(e.target.value)}
              rows={6}
              placeholder={pathogenMode === "fasta" ? EXAMPLE_FASTA : EXAMPLE_TEXT}
              style={{
                width: "100%", padding: "12px", background: "rgba(255,255,255,0.05)", border: `1px solid ${C.border}`,
                borderRadius: 10, color: C.text, fontSize: 12, fontFamily: pathogenMode === "fasta" ? "monospace" : "inherit",
                outline: "none", resize: "vertical", boxSizing: "border-box", lineHeight: 1.6,
              }}
            />

            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={() => setPathogenInput(pathogenMode === "fasta" ? EXAMPLE_FASTA : EXAMPLE_TEXT)}
                style={{ padding: "5px 12px", background: "rgba(255,255,255,0.06)", border: `1px solid ${C.border}`, borderRadius: 6, color: C.muted, fontSize: 11, cursor: "pointer" }}>
                Load Example
              </button>
              <button onClick={() => setPathogenInput("")}
                style={{ padding: "5px 12px", background: "rgba(255,255,255,0.06)", border: `1px solid ${C.border}`, borderRadius: 6, color: C.muted, fontSize: 11, cursor: "pointer" }}>
                Clear
              </button>
            </div>

            <div style={{ marginTop: 10, padding: "8px 12px", background: "rgba(108,99,255,0.08)", borderRadius: 8, fontSize: 11, color: C.accent }}>
              {pathogenMode === "fasta"
                ? "✓ FASTA sequences are encoded directly by ESM-2 650M for maximum accuracy"
                : "✓ Text descriptions trigger ChEMBL keyword lookup → protein family embeddings via ESM-2"}
            </div>
          </div>

          {/* Drug Panel */}
          <div style={{ padding: "20px", background: C.surface, borderRadius: 16, border: `1px solid ${C.border}` }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>💊 Drug Combination</h3>
              <span style={{ fontSize: 11, color: C.muted }}>Enter name OR SMILES — auto-detected</span>
            </div>

            {drugs.map((drug, idx) => (
              <DrugRow key={idx} idx={idx} drug={drug} onChange={updateDrug} onRemove={removeDrug} />
            ))}

            {drugs.length < 5 && (
              <button onClick={addDrug}
                style={{ width: "100%", padding: "10px", background: "rgba(108,99,255,0.08)", border: `1px dashed ${C.accent}44`, borderRadius: 10, color: C.accent, fontSize: 13, cursor: "pointer" }}>
                + Add Another Drug
              </button>
            )}

            {/* Ratio visualization */}
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, color: C.muted, marginBottom: 6 }}>Composition Ratios</div>
              <div style={{ display: "flex", height: 6, borderRadius: 4, overflow: "hidden" }}>
                {["#6c63ff", "#22d3a0", "#f59e0b", "#06b6d4", "#ef4444"].map((col, i) => {
                  const d = drugs[i];
                  if (!d) return null;
                  const total = drugs.reduce((s, x) => s + x.ratio, 0) || 1;
                  return <div key={i} style={{ flex: d.ratio / total, background: col, transition: "flex 0.5s" }} />;
                })}
              </div>
            </div>
          </div>

          {/* Patient Panel */}
          <div style={{ padding: "20px", background: C.surface, borderRadius: 16, border: `1px solid ${C.border}` }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, marginBottom: 16 }}>👤 Patient Profile</h3>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 14 }}>
              {[
                { key: "age", label: "Age", unit: "yrs", min: 1, max: 100 },
                { key: "weight", label: "Weight", unit: "kg", min: 20, max: 200 },
                { key: "gfr", label: "GFR", unit: "mL/min", min: 5, max: 120 },
              ].map(f => (
                <div key={f.key}>
                  <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>{f.label} ({f.unit})</label>
                  <input type="number" min={f.min} max={f.max}
                    value={patient[f.key]}
                    onChange={e => setPatient(p => ({ ...p, [f.key]: parseFloat(e.target.value) }))}
                    style={{ width: "100%", padding: "8px 10px", background: "rgba(255,255,255,0.06)", border: `1px solid ${C.border}`, borderRadius: 8, color: C.text, fontSize: 13, boxSizing: "border-box" }}
                  />
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 14 }}>
              {[
                { key: "ast", label: "AST (liver)", unit: "IU/L", min: 5, max: 500 },
                { key: "alt", label: "ALT (liver)", unit: "IU/L", min: 5, max: 500 },
              ].map(f => (
                <div key={f.key}>
                  <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>{f.label}</label>
                  <input type="number" min={f.min} max={f.max}
                    value={patient[f.key]}
                    onChange={e => setPatient(p => ({ ...p, [f.key]: parseFloat(e.target.value) }))}
                    style={{ width: "100%", padding: "8px 10px", background: "rgba(255,255,255,0.06)", border: `1px solid ${C.border}`, borderRadius: 8, color: C.text, fontSize: 13, boxSizing: "border-box" }}
                  />
                </div>
              ))}
              <div>
                <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>Sex</label>
                <select value={patient.sex} onChange={e => setPatient(p => ({ ...p, sex: e.target.value }))}
                  style={{ width: "100%", padding: "8px 10px", background: "rgba(255,255,255,0.06)", border: `1px solid ${C.border}`, borderRadius: 8, color: C.text, fontSize: 13, boxSizing: "border-box" }}>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
              </div>
            </div>

            <div>
              <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 8 }}>Comorbidities</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {COMORBIDITIES.map(c => {
                  const active = patient.comorbidities.includes(c);
                  return (
                    <button key={c} onClick={() => toggleComorbidity(c)}
                      style={{
                        padding: "4px 10px", borderRadius: 20, border: `1px solid ${active ? C.accent : C.border}`,
                        background: active ? `${C.accent}22` : "transparent", color: active ? C.accent : C.muted,
                        fontSize: 11, cursor: "pointer", textTransform: "capitalize",
                      }}>
                      {c.replace(/_/g, " ")}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Analyze Button */}
          <button onClick={handleAnalyze} disabled={loading}
            style={{
              padding: "16px", background: loading ? "rgba(108,99,255,0.3)" : `linear-gradient(135deg, ${C.accent}, ${C.teal})`,
              border: "none", borderRadius: 14, color: "#fff", fontSize: 16, fontWeight: 800, cursor: loading ? "wait" : "pointer",
              letterSpacing: 0.5, boxShadow: loading ? "none" : `0 4px 24px ${C.accentGlow}`,
              transition: "all 0.2s",
            }}>
            {loading ? "🔬 Analyzing... (ESM-2 encoding pathogen)" : "🔬 Run Drug Efficacy Analysis"}
          </button>

          {error && (
            <div style={{ padding: "12px 16px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 10, color: C.danger, fontSize: 13 }}>
              ⚠ {error}
            </div>
          )}
        </div>

        {/* ─── RIGHT COLUMN: Results ──────────────────────────────────────────── */}
        <div>
          {!result && !loading && (
            <div style={{ padding: "60px 30px", background: C.surface, borderRadius: 16, border: `1px solid ${C.border}`, textAlign: "center" }}>
              <div style={{ fontSize: 56, marginBottom: 16 }}>🧬</div>
              <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>Ready for Analysis</div>
              <div style={{ color: C.muted, fontSize: 13, maxWidth: 320, margin: "0 auto" }}>
                Enter a pathogen description or FASTA sequence, add your drug combination, and configure the patient profile to predict treatment efficacy.
              </div>
              <div style={{ marginTop: 24, padding: "12px 20px", background: `${C.accent}11`, borderRadius: 12, border: `1px solid ${C.accent}22`, fontSize: 12, color: C.muted }}>
                Works with <strong style={{ color: C.accent }}>any novel pathogen</strong> — no existing drugs or trials required
              </div>
            </div>
          )}

          {loading && (
            <div style={{ padding: "60px 30px", background: C.surface, borderRadius: 16, border: `1px solid ${C.border}`, textAlign: "center" }}>
              <div style={{ width: 50, height: 50, border: `3px solid ${C.accent}33`, borderTop: `3px solid ${C.accent}`, borderRadius: "50%", animation: "spin 1s linear infinite", margin: "0 auto 24px" }} />
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Encoding pathogen proteins...</div>
              <div style={{ color: C.muted, fontSize: 13 }}>ESM-2 650M → cross-attention with drug embeddings → patient PK adjustment</div>
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            </div>
          )}

          {result && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* Summary banner */}
              <div style={{ padding: "16px 20px", background: `linear-gradient(135deg, ${C.accent}22, ${C.teal}11)`, borderRadius: 14, border: `1px solid ${C.accent}33` }}>
                <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 4 }}>{result.recommendation?.summary}</div>
                <div style={{ fontSize: 12, color: C.muted }}>
                  Inference: {result.inference_time_ms}ms •
                  Mode: {result.pathogen?.input_mode === "fasta" ? "FASTA/ESM-2" : "Text/Keyword"} •
                  Trained model
                </div>
              </div>

              {/* Tabs */}
              <div style={{ display: "flex", gap: 2, background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: 3 }}>
                {[["efficacy", "📊 Efficacy"], ["toxicity", "⚗️ Toxicity"], ["mechanism", "🧠 Mechanism"], ["pk", "🔬 PK/PD"], ["recommendation", "📋 Plan"]].map(([tab, label]) => (
                  <button key={tab} onClick={() => setActiveTab(tab)}
                    style={{
                      flex: 1, padding: "7px 4px", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 12, fontWeight: activeTab === tab ? 700 : 400,
                      background: activeTab === tab ? C.accent : "transparent",
                      color: activeTab === tab ? "#fff" : C.muted,
                    }}>{label}</button>
                ))}
              </div>

              {/* Tab content */}
              <div style={{ padding: "20px", background: C.surface, borderRadius: 14, border: `1px solid ${C.border}` }}>
                {activeTab === "efficacy" && result.efficacy && (
                  <div>
                    <EfficacyGauge
                      value={result.efficacy.patient_adjusted_percent}
                      ciLow={result.efficacy.confidence_interval?.[0]}
                      ciHigh={result.efficacy.confidence_interval?.[1]}
                    />
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 14 }}>
                      {[
                        { label: "Base Efficacy", value: `${Math.round(result.efficacy.base_score * 100)}%` },
                        { label: "Patient-Adjusted", value: `${result.efficacy.patient_adjusted_percent}%` },
                        { label: "Predicted pIC50", value: result.efficacy.predicted_pic50 || "N/A" },
                        { label: "Pred. IC50 (nM)", value: result.efficacy.predicted_ic50_nM ? `${result.efficacy.predicted_ic50_nM} nM` : "N/A" },
                        { label: "Patient Multiplier", value: `×${result.efficacy.efficacy_multiplier}` },
                      ].map(it => (
                        <div key={it.label} style={{ padding: "10px 12px", background: "rgba(255,255,255,0.03)", borderRadius: 8 }}>
                          <div style={{ fontSize: 11, color: C.muted }}>{it.label}</div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: C.teal }}>{it.value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {activeTab === "toxicity" && result.toxicity && (
                  <ToxBadge cls={result.toxicity.class} probs={result.toxicity.probabilities} />
                )}

                {activeTab === "mechanism" && result.mechanism && (
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>Mechanism Summary</div>
                    <div style={{ padding: "12px 14px", background: `${C.teal}11`, borderRadius: 10, border: `1px solid ${C.teal}22`, color: C.text, fontSize: 12, lineHeight: 1.7, marginBottom: 14 }}>
                      {result.mechanism.summary}
                    </div>

                    <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Pathogen Target Families</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8, marginBottom: 14 }}>
                      {result.mechanism.pathogen_targets?.map((item, i) => (
                        <div key={i} style={{ padding: "10px 12px", background: "rgba(255,255,255,0.03)", borderRadius: 8, border: `1px solid ${C.border}` }}>
                          <div style={{ fontSize: 11, color: C.muted, marginBottom: 2 }}>Signal</div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: C.accent }}>{item.pathogen_signal}</div>
                          <div style={{ fontSize: 12, color: C.text, marginTop: 4 }}>{item.target_family}</div>
                        </div>
                      ))}
                    </div>

                    <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Drug Actions</div>
                    {result.mechanism.drug_actions?.map((item, i) => (
                      <div key={i} style={{ padding: "10px 12px", background: "rgba(255,255,255,0.03)", borderRadius: 8, border: `1px solid ${C.border}`, marginBottom: 8 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                          <span style={{ fontWeight: 700 }}>{item.drug}</span>
                          <span style={{ color: C.muted }}>{Math.round((item.ratio || 0) * 100)}%</span>
                        </div>
                        <div style={{ fontSize: 12, color: C.text, marginTop: 4 }}>{item.predicted_action}</div>
                        <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>Confidence: {item.confidence}</div>
                      </div>
                    ))}
                  </div>
                )}

                {activeTab === "pk" && result.patient_pk && (
                  <div>
                    <PKPanel pk={result.patient_pk} />
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: C.muted }}>Patient Adjustment Factors</div>
                      {Object.entries(result.patient_pk.factors || {}).map(([k, v]) => (
                        <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}>
                          <span style={{ color: C.muted, textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</span>
                          <span style={{ color: v >= 0.8 ? C.success : v >= 0.5 ? C.warning : C.danger, fontWeight: 600 }}>
                            {typeof v === "number" ? v.toFixed(3) : v}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {activeTab === "recommendation" && result.recommendation && (
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>Suggested Dosing Frequency</div>
                    <div style={{ padding: "10px 14px", background: `${C.teal}11`, borderRadius: 10, fontSize: 13, color: C.teal, fontWeight: 600, marginBottom: 14 }}>
                      🕐 {result.recommendation.suggested_dosing_frequency}
                    </div>
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>Patient-Specific Notes</div>
                    {result.recommendation.dosage_adjustment_notes?.map((note, i) => (
                      <div key={i} style={{ display: "flex", gap: 8, padding: "7px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}>
                        <span>⚠</span><span style={{ color: C.text }}>{note}</span>
                      </div>
                    ))}
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8, marginTop: 14 }}>Monitoring Plan</div>
                    {result.recommendation.monitoring?.map((m, i) => (
                      <div key={i} style={{ display: "flex", gap: 8, padding: "7px 0", borderBottom: `1px solid ${C.border}`, fontSize: 12 }}>
                        <span style={{ color: C.success }}>✓</span><span>{m}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Drugs resolved */}
              {result.drugs && (
                <div style={{ padding: "14px 16px", background: C.surface, borderRadius: 12, border: `1px solid ${C.border}` }}>
                  <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: C.muted }}>Resolved Drug Inputs</div>
                  {result.drugs.map((d, i) => (
                    <div key={i} style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>
                      <strong style={{ color: C.text }}>{d.drug_name || d.input}</strong> — {Math.round(d.ratio * 100)}%
                      {d.resolved_smiles && <span style={{ color: C.border }}> • {d.resolved_smiles.slice(0, 30)}...</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
