class H {
  constructor(t, a) {
    this.http = t, this.base = a;
  }
  http;
  base;
  async list() {
    return (await this.http.get(`${this.base}/bills/`)).data;
  }
  async get(t) {
    return (await this.http.get(`${this.base}/bills/${t}/`)).data;
  }
  async upload(t) {
    const a = new FormData();
    return a.append("file", t), (await this.http.post(`${this.base}/bills/`, a)).data;
  }
  async update(t, a) {
    return (await this.http.patch(`${this.base}/bills/${t}/`, a)).data;
  }
  async updateLine(t, a, o) {
    return (await this.http.patch(`${this.base}/bills/${t}/lines/${a}/`, o)).data;
  }
  async extract(t) {
    return (await this.http.post(`${this.base}/bills/${t}/extract/`)).data;
  }
  async confirm(t, a) {
    return (await this.http.post(`${this.base}/bills/${t}/confirm/`, { location: a })).data;
  }
  async remove(t) {
    await this.http.delete(`${this.base}/bills/${t}/`);
  }
  async search(t, a) {
    const { url: o, params: m, label: n } = K[t], h = await this.http.get(o, {
      params: { ...m, search: a, limit: 20 }
    });
    return (Array.isArray(h.data) ? h.data : h.data.results).map((p) => ({ value: String(p.pk), label: n(p) }));
  }
}
const K = {
  part: {
    url: "/api/part/",
    params: { active: !0, purchaseable: !0 },
    label: (e) => e.IPN ? `${e.IPN} | ${e.name}` : e.name
  },
  supplier: {
    url: "/api/company/",
    params: { is_supplier: !0, active: !0 },
    label: (e) => e.name
  },
  location: {
    url: "/api/stock/location/",
    params: {},
    label: (e) => e.pathstring ?? e.name
  }
};
function q(e) {
  const t = e?.response?.data;
  if (typeof t == "string") return t.slice(0, 300);
  if (t && typeof t == "object") {
    const a = Object.values(t)[0];
    return Array.isArray(a) ? String(a[0]) : String(a);
  }
  return e?.message ?? "Request failed";
}
var Q = {
  outline: {
    xmlns: "http://www.w3.org/2000/svg",
    width: 24,
    height: 24,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  },
  filled: {
    xmlns: "http://www.w3.org/2000/svg",
    width: 24,
    height: 24,
    viewBox: "0 0 24 24",
    fill: "currentColor",
    stroke: "none"
  }
};
const W = window.React.forwardRef, S = window.React.createElement, Y = (e, t, a, o) => {
  const m = W(
    ({
      color: n = "currentColor",
      size: h = 24,
      stroke: r = 2,
      title: p,
      className: T,
      children: f,
      ...E
    }, b) => S(
      "svg",
      {
        ref: b,
        ...Q[e],
        width: h,
        height: h,
        className: ["tabler-icon", `tabler-icon-${t}`, T].filter(Boolean).join(" "),
        strokeWidth: r,
        stroke: n,
        ...E
      },
      [
        p && S("title", { key: "svg-title" }, p),
        ...o.map(([k, g]) => S(k, g)),
        ...Array.isArray(f) ? f : [f]
      ]
    )
  );
  return m.displayName = `${a}`, m;
};
const J = [["path", { d: "M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2", key: "svg-0" }], ["path", { d: "M7 9l5 -5l5 5", key: "svg-1" }], ["path", { d: "M12 4l0 12", key: "svg-2" }]], X = Y("outline", "upload", "Upload", J);
function Z(e) {
  return e.part ? Math.min(e.confidence, e.match_confidence) : 0;
}
function ee(e, t) {
  return e.skip ? "high" : e.part ? Z(e) < t ? "low" : "high" : "missing";
}
const te = {
  high: void 0,
  low: "var(--mantine-color-yellow-light)",
  missing: "var(--mantine-color-red-light)"
};
function N(e) {
  return `${Math.round(e * 100)}%`;
}
function A(e, t) {
  return e >= t ? "green" : e >= t / 2 ? "yellow" : "red";
}
const F = {
  pending: "gray",
  processing: "blue",
  retry: "orange",
  failed: "red",
  review: "yellow",
  completed: "green"
}, ne = ["pending", "processing", "retry"];
function z(e) {
  return ne.includes(e.status);
}
function ae(e) {
  if (e.status !== "review") return "Only bills under review can be received.";
  if (!e.supplier) return "Choose the supplier first.";
  const t = e.lines.filter((o) => !o.skip);
  if (t.length === 0) return "Every line is skipped.";
  const a = t.filter((o) => !o.part).length;
  return a > 0 ? `${a} line(s) have no part. Pick a part or skip them.` : null;
}
const re = window.MantineCore.Alert, le = window.MantineCore.Badge, ce = window.MantineCore.Button, oe = window.MantineCore.FileButton, ie = window.MantineCore.Group, se = window.MantineCore.Stack, w = window.MantineCore.Table, P = window.MantineCore.Text, i = window.React, ue = "application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif";
function de({
  bills: e,
  selected: t,
  uploading: a,
  hasApiKey: o,
  maxUploadMb: m,
  onUpload: n,
  onSelect: h
}) {
  return /* @__PURE__ */ i.createElement(se, { gap: "sm" }, !o && /* @__PURE__ */ i.createElement(re, { color: "orange", title: "Gemini API key missing" }, "Ask an administrator to set the key in the Bill Scanner plugin settings."), /* @__PURE__ */ i.createElement(ie, { justify: "space-between" }, /* @__PURE__ */ i.createElement(P, { size: "sm", c: "dimmed" }, "Upload a photo or PDF of a supplier bill (up to ", m, " MB)."), /* @__PURE__ */ i.createElement(oe, { onChange: (r) => r && n(r), accept: ue }, (r) => /* @__PURE__ */ i.createElement(ce, { ...r, leftSection: /* @__PURE__ */ i.createElement(X, { size: 16 }), loading: a }, "Upload bill"))), e.length === 0 ? /* @__PURE__ */ i.createElement(P, { c: "dimmed" }, "No bills scanned yet.") : /* @__PURE__ */ i.createElement(w, { highlightOnHover: !0, striped: !0, "aria-label": "Scanned bills" }, /* @__PURE__ */ i.createElement(w.Thead, null, /* @__PURE__ */ i.createElement(w.Tr, null, /* @__PURE__ */ i.createElement(w.Th, null, "File"), /* @__PURE__ */ i.createElement(w.Th, null, "Supplier"), /* @__PURE__ */ i.createElement(w.Th, null, "Bill number"), /* @__PURE__ */ i.createElement(w.Th, null, "Date"), /* @__PURE__ */ i.createElement(w.Th, null, "Lines"), /* @__PURE__ */ i.createElement(w.Th, null, "Status"))), /* @__PURE__ */ i.createElement(w.Tbody, null, e.map((r) => /* @__PURE__ */ i.createElement(
    w.Tr,
    {
      key: r.pk,
      onClick: () => h(r),
      style: { cursor: "pointer" },
      bg: r.pk === t ? "var(--mantine-color-blue-light)" : void 0
    },
    /* @__PURE__ */ i.createElement(w.Td, null, r.file_name),
    /* @__PURE__ */ i.createElement(w.Td, null, r.supplier_detail?.name ?? r.supplier_name),
    /* @__PURE__ */ i.createElement(w.Td, null, r.bill_number),
    /* @__PURE__ */ i.createElement(w.Td, null, r.bill_date ?? ""),
    /* @__PURE__ */ i.createElement(w.Td, null, r.lines.length),
    /* @__PURE__ */ i.createElement(w.Td, null, /* @__PURE__ */ i.createElement(le, { color: F[r.status] }, r.status_label))
  )))));
}
const pe = window.MantineCore.Select, me = window.React, he = window.React.useEffect, L = window.React.useState;
function x({
  label: e,
  placeholder: t,
  value: a,
  initial: o,
  disabled: m,
  search: n,
  onChange: h
}) {
  const [r, p] = L(""), [T, f] = L(o ? [o] : []);
  return he(() => {
    let E = !1;
    const b = setTimeout(() => {
      n(r).then((k) => {
        if (E) return;
        const g = o && !k.some((s) => s.value === o.value) ? [o, ...k] : k;
        f(g);
      }).catch(() => {
      });
    }, 250);
    return () => {
      E = !0, clearTimeout(b);
    };
  }, [r]), /* @__PURE__ */ me.createElement(
    pe,
    {
      label: e,
      placeholder: t,
      data: T,
      value: a,
      searchable: !0,
      clearable: !0,
      disabled: m,
      filter: ({ options: E }) => E,
      onSearchChange: p,
      onChange: h,
      nothingFoundMessage: "No matches",
      comboboxProps: { withinPortal: !0 }
    }
  );
}
const $ = window.MantineCore.Badge, we = window.MantineCore.Checkbox, U = window.MantineCore.NumberInput, d = window.MantineCore.Table, ge = window.MantineCore.Text, fe = window.MantineCore.Tooltip, l = window.React, Ee = {
  supplier_sku: "Supplier SKU",
  sku: "Other supplier SKU",
  mpn: "MPN",
  ipn: "IPN",
  name: "Name",
  manual: "Chosen",
  "": "No match"
};
function ke(e) {
  const t = e.part_detail;
  return t ? { value: String(t.pk), label: t.IPN ? `${t.IPN} | ${t.name}` : t.name } : null;
}
function Te({ lines: e, threshold: t, editable: a, searchParts: o, onChange: m }) {
  return /* @__PURE__ */ l.createElement(d, { "aria-label": "Bill lines", verticalSpacing: "xs" }, /* @__PURE__ */ l.createElement(d.Thead, null, /* @__PURE__ */ l.createElement(d.Tr, null, /* @__PURE__ */ l.createElement(d.Th, null, "#"), /* @__PURE__ */ l.createElement(d.Th, null, "Description on bill"), /* @__PURE__ */ l.createElement(d.Th, null, "SKU"), /* @__PURE__ */ l.createElement(d.Th, { w: 110 }, "Quantity"), /* @__PURE__ */ l.createElement(d.Th, { w: 130 }, "Unit price"), /* @__PURE__ */ l.createElement(d.Th, null, "Read"), /* @__PURE__ */ l.createElement(d.Th, { miw: 260 }, "Part"), /* @__PURE__ */ l.createElement(d.Th, null, "Match"), /* @__PURE__ */ l.createElement(d.Th, null, "Skip"))), /* @__PURE__ */ l.createElement(d.Tbody, null, e.map((n) => {
    const h = ee(n, t);
    return /* @__PURE__ */ l.createElement(d.Tr, { key: n.pk, bg: te[h], "data-level": h }, /* @__PURE__ */ l.createElement(d.Td, null, n.line_number), /* @__PURE__ */ l.createElement(d.Td, null, /* @__PURE__ */ l.createElement(ge, { size: "sm", td: n.skip ? "line-through" : void 0 }, n.description)), /* @__PURE__ */ l.createElement(d.Td, null, n.sku), /* @__PURE__ */ l.createElement(d.Td, null, /* @__PURE__ */ l.createElement(
      U,
      {
        "aria-label": `Quantity line ${n.line_number}`,
        size: "xs",
        min: 0,
        defaultValue: Number(n.quantity),
        disabled: !a,
        onBlur: (r) => {
          const p = r.currentTarget.value.replace(/,/g, "");
          p && Number(p) !== Number(n.quantity) && m(n, { quantity: p });
        }
      }
    )), /* @__PURE__ */ l.createElement(d.Td, null, /* @__PURE__ */ l.createElement(
      U,
      {
        "aria-label": `Unit price line ${n.line_number}`,
        size: "xs",
        min: 0,
        decimalScale: 6,
        defaultValue: n.unit_price === null ? "" : Number(n.unit_price),
        disabled: !a,
        onBlur: (r) => {
          const p = r.currentTarget.value.replace(/,/g, ""), T = n.unit_price === null ? "" : String(Number(n.unit_price));
          p !== T && m(n, { unit_price: p === "" ? null : p });
        }
      }
    )), /* @__PURE__ */ l.createElement(d.Td, null, /* @__PURE__ */ l.createElement(fe, { label: "How clearly Gemini could read this line" }, /* @__PURE__ */ l.createElement($, { variant: "light", color: A(n.confidence, t) }, N(n.confidence)))), /* @__PURE__ */ l.createElement(d.Td, null, /* @__PURE__ */ l.createElement(
      x,
      {
        placeholder: "Search parts",
        value: n.part ? String(n.part) : null,
        initial: ke(n),
        disabled: !a,
        search: o,
        onChange: (r) => m(n, { part: r ? Number(r) : null })
      }
    )), /* @__PURE__ */ l.createElement(d.Td, null, n.part ? /* @__PURE__ */ l.createElement($, { variant: "light", color: A(n.match_confidence, t) }, Ee[n.match_method] ?? n.match_method, " ", N(n.match_confidence)) : /* @__PURE__ */ l.createElement($, { variant: "light", color: "red" }, "No part")), /* @__PURE__ */ l.createElement(d.Td, null, /* @__PURE__ */ l.createElement(
      we,
      {
        "aria-label": `Skip line ${n.line_number}`,
        checked: n.skip,
        disabled: !a,
        onChange: (r) => m(n, { skip: r.currentTarget.checked })
      }
    )));
  })));
}
const be = window.MantineCore.Alert, I = window.MantineCore.Anchor, ye = window.MantineCore.Badge, M = window.MantineCore.Button, C = window.MantineCore.Group, ve = window.MantineCore.Paper, Ce = window.MantineCore.Stack, O = window.MantineCore.Text, B = window.MantineCore.TextInput, _e = window.MantineCore.Title, u = window.React, D = window.React.useState;
function Se({
  bill: e,
  client: t,
  threshold: a,
  canEdit: o,
  canConfirm: m,
  onChanged: n,
  onDeleted: h,
  onError: r
}) {
  const [p, T] = D(null), [f, E] = D(!1), b = o && e.status === "review", k = ae(e);
  async function g(c) {
    E(!0);
    try {
      const v = await c();
      v && n(v);
    } catch (v) {
      r(v);
    } finally {
      E(!1);
    }
  }
  const s = (c) => g(() => t.update(e.pk, c)), y = (c, v) => g(async () => (await t.updateLine(e.pk, c.pk, v), t.get(e.pk)));
  return /* @__PURE__ */ u.createElement(ve, { withBorder: !0, p: "md" }, /* @__PURE__ */ u.createElement(Ce, { gap: "md" }, /* @__PURE__ */ u.createElement(C, { justify: "space-between" }, /* @__PURE__ */ u.createElement(C, null, /* @__PURE__ */ u.createElement(_e, { order: 4 }, e.file_name), /* @__PURE__ */ u.createElement(ye, { color: F[e.status] }, e.status_label)), e.file_url && /* @__PURE__ */ u.createElement(I, { href: e.file_url, target: "_blank", rel: "noreferrer" }, "Open original")), e.error && /* @__PURE__ */ u.createElement(be, { color: e.status === "failed" ? "red" : "orange", title: "Extraction problem" }, e.error, " (attempt ", e.attempts, ")"), z(e) && /* @__PURE__ */ u.createElement(O, { c: "dimmed" }, "Gemini is reading this bill..."), e.status !== "pending" && e.status !== "processing" && /* @__PURE__ */ u.createElement(C, { grow: !0, align: "flex-end" }, /* @__PURE__ */ u.createElement(
    x,
    {
      label: `Supplier (bill says "${e.supplier_name}")`,
      value: e.supplier ? String(e.supplier) : null,
      initial: e.supplier_detail ? { value: String(e.supplier_detail.pk), label: e.supplier_detail.name } : null,
      disabled: !b,
      search: (c) => t.search("supplier", c),
      onChange: (c) => s({ supplier: c ? Number(c) : null })
    }
  ), /* @__PURE__ */ u.createElement(
    B,
    {
      label: "Bill number",
      defaultValue: e.bill_number,
      disabled: !b,
      onBlur: (c) => c.currentTarget.value !== e.bill_number && s({ bill_number: c.currentTarget.value })
    }
  ), /* @__PURE__ */ u.createElement(
    B,
    {
      label: "Bill date",
      type: "date",
      defaultValue: e.bill_date ?? "",
      disabled: !b,
      onBlur: (c) => c.currentTarget.value !== (e.bill_date ?? "") && s({ bill_date: c.currentTarget.value || null })
    }
  ), /* @__PURE__ */ u.createElement(
    B,
    {
      label: "Currency",
      maxLength: 3,
      defaultValue: e.currency,
      disabled: !b,
      onBlur: (c) => c.currentTarget.value.toUpperCase() !== e.currency && s({ currency: c.currentTarget.value.toUpperCase() })
    }
  )), e.lines.length > 0 && /* @__PURE__ */ u.createElement(
    Te,
    {
      lines: e.lines,
      threshold: a,
      editable: b,
      searchParts: (c) => t.search("part", c),
      onChange: y
    }
  ), /* @__PURE__ */ u.createElement(C, { justify: "space-between" }, /* @__PURE__ */ u.createElement(C, null, o && (e.status === "failed" || e.status === "review") && /* @__PURE__ */ u.createElement(M, { variant: "default", disabled: f, onClick: () => g(() => t.extract(e.pk)) }, "Read again"), o && e.status !== "completed" && /* @__PURE__ */ u.createElement(
    M,
    {
      color: "red",
      variant: "subtle",
      disabled: f,
      onClick: () => {
        window.confirm("Delete this bill?") && g(async () => {
          await t.remove(e.pk), h();
        });
      }
    },
    "Delete"
  )), e.status === "review" && m && /* @__PURE__ */ u.createElement(C, { align: "flex-end" }, /* @__PURE__ */ u.createElement(
    x,
    {
      placeholder: "Receive into location",
      value: p,
      search: (c) => t.search("location", c),
      onChange: T
    }
  ), /* @__PURE__ */ u.createElement(
    M,
    {
      color: "green",
      loading: f,
      disabled: k !== null,
      title: k ?? void 0,
      onClick: () => g(() => t.confirm(e.pk, p ? Number(p) : null))
    },
    "Create order and receive"
  )), e.purchase_order && /* @__PURE__ */ u.createElement(I, { href: `/web/purchasing/purchase-order/${e.purchase_order}/` }, "View purchase order")), e.status === "review" && k && /* @__PURE__ */ u.createElement(O, { size: "sm", c: "dimmed" }, k)));
}
const $e = window.MantineCore.Stack, j = window.MantineNotifications.notifications, _ = window.React, G = window.React.useCallback, V = window.React.useEffect, Me = window.React.useMemo, R = window.React.useState, Be = 3e3;
function Re({ context: e }) {
  const t = e.context, a = Me(() => new H(e.api, t.api), [e.api]), [o, m] = R([]), [n, h] = R(null), [r, p] = R(!1), T = G((s) => {
    j.show({ color: "red", title: "Bill scanner", message: q(s) });
  }, []), f = G(
    () => a.list().then(m).catch(T),
    [a]
  );
  V(() => {
    f();
  }, [f]);
  const E = o.some(z);
  V(() => {
    if (!E) return;
    const s = setInterval(f, Be);
    return () => clearInterval(s);
  }, [E, f]);
  const b = (s) => m((y) => y.map((c) => c.pk === s.pk ? s : c));
  async function k(s) {
    p(!0);
    try {
      const y = await a.upload(s);
      m((c) => [y, ...c]), h(y.pk);
    } catch (y) {
      T(y);
    } finally {
      p(!1);
    }
  }
  const g = o.find((s) => s.pk === n) ?? null;
  return /* @__PURE__ */ _.createElement($e, { gap: "lg" }, /* @__PURE__ */ _.createElement(
    de,
    {
      bills: o,
      selected: n,
      uploading: r,
      hasApiKey: t.has_api_key,
      maxUploadMb: t.max_upload_mb,
      onUpload: k,
      onSelect: (s) => h(s.pk)
    }
  ), g && /* @__PURE__ */ _.createElement(
    Se,
    {
      key: `${g.pk}-${g.status}-${g.supplier}`,
      bill: g,
      client: a,
      threshold: t.low_confidence,
      canEdit: t.can_edit,
      canConfirm: t.can_confirm,
      onChanged: (s) => {
        b(s), s.status === "completed" && j.show({ color: "green", title: "Bill received", message: "Purchase order created." });
      },
      onDeleted: () => {
        h(null), m((s) => s.filter((y) => y.pk !== g.pk));
      },
      onError: T
    }
  ));
}
function xe(e) {
  return /* @__PURE__ */ _.createElement(Re, { context: e });
}
export {
  Re as BillScannerPanel,
  xe as renderBillScannerPanel
};
//# sourceMappingURL=BillScanner.js.map
