import type { FieldAuthority } from "@finai/contracts";

const authorityFields: FieldAuthority[] = [
  {
    field: "account_code",
    state: "OBSERVED",
    authoritative: true,
    evidence_ids: ["ev_tb_2026_08"],
    source_path: "sheet:TB!A:A",
    dependencies: [],
    rationale: "Directly declared by the source authority contract.",
  },
  {
    field: "net_balance",
    state: "DERIVED",
    authoritative: true,
    evidence_ids: ["ev_tb_2026_08"],
    rule_id: "finance.tb.net-balance",
    rule_version: 1,
    dependencies: ["debit", "credit"],
    rationale: "Deterministically derived from observed dependencies.",
  },
  {
    field: "account_semantic_class",
    state: "INFERRED",
    authoritative: false,
    evidence_ids: [],
    dependencies: [],
    rationale: "Candidate interpretation requires human review and supporting evidence.",
  },
  {
    field: "customer_invoice_id",
    state: "UNAVAILABLE",
    authoritative: false,
    evidence_ids: [],
    dependencies: [],
    rationale: "A trial balance cannot establish invoice-level evidence.",
  },
];

const stages = [
  ["01", "Evidence received", "Immutable hash retained"],
  ["02", "Authority compiled", "Exact scope enforced"],
  ["03", "Validation pending", "No canonical promotion"],
];

export default function Home() {
  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brandMark">F</span>
          <div>
            <strong>FinAI</strong>
            <span>NYX CORE</span>
          </div>
        </div>
        <div className="context">
          <span>Legal entity · GE-001</span>
          <span>Period · 2026-08</span>
          <span>Currency · GEL</span>
        </div>
        <div className="environment">LOCAL · CANDIDATE</div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">ENTERPRISE HYDRATION / SOURCE AUTHORITY</p>
          <h1>Construct what the evidence can prove.</h1>
          <p className="heroCopy">
            A trial balance hydrates the prebuilt finance operating model without inventing
            transactions, documents, or authority absent from the source.
          </p>
        </div>
        <div className="receipt">
          <span>CONSTRUCTION RECEIPT</span>
          <strong>cr_93e4a66f0d851c72829bb113</strong>
          <small>Candidate only · promotion requires reconciliation and approval</small>
        </div>
      </section>

      <section className="stageGrid" aria-label="Hydration stages">
        {stages.map(([number, title, detail]) => (
          <article key={number} className="stage">
            <span>{number}</span>
            <div>
              <strong>{title}</strong>
              <p>{detail}</p>
            </div>
          </article>
        ))}
      </section>

      <section className="workspace">
        <aside className="sourcePanel">
          <p className="panelLabel">SOURCE AUTHORITY CONTRACT</p>
          <dl>
            <div><dt>Source kind</dt><dd>Trial balance</dd></div>
            <div><dt>Evidence</dt><dd>tb-2026-08.xlsx</dd></div>
            <div><dt>Tenant</dt><dd>805d8a32…</dd></div>
            <div><dt>Entity</dt><dd>entity-ge-001</dd></div>
            <div><dt>Period</dt><dd>2026-08</dd></div>
            <div><dt>Currency</dt><dd>GEL</dd></div>
          </dl>
          <div className="hash">
            <span>SHA-256</span>
            <code>aaaaaaaaaaaa…aaaaaaaa</code>
          </div>
        </aside>

        <section className="authorityPanel">
          <div className="panelHeader">
            <div>
              <p className="panelLabel">FIELD AUTHORITY</p>
              <h2>Hydrated finance model</h2>
            </div>
            <span className="count">{authorityFields.length} fields</span>
          </div>
          <div className="fieldTable" role="table" aria-label="Field authority assessment">
            <div className="tableHead" role="row">
              <span>Field</span><span>State</span><span>Authority basis</span>
            </div>
            {authorityFields.map((item) => (
              <div className="tableRow" role="row" key={item.field}>
                <code>{item.field}</code>
                <span className={`badge badge-${item.state.toLowerCase()}`}>{item.state}</span>
                <p>{item.rationale}</p>
              </div>
            ))}
          </div>
        </section>
      </section>

      <footer>
        <span>Known · how it is known · whether it is authoritative</span>
        <span>Compiler authority-compiler/0.1</span>
      </footer>
    </main>
  );
}
