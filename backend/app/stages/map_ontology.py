"""Ontology-mapping stage — applies the multi-strategy matching ensemble.

Wires each extracted ``LineItem`` through ``services.mapping.OntologyMatcher`` and
records the winning canonical key, method, and per-strategy confidence. The ontology
+ locale come from the extraction job; adapters (embedding/LLM) are pulled from the
registry when configured.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext
from app.services.mapping import OntologyMatcher


class MapOntologyStage:
    name = "map_ontology"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        ontology = getattr(ctx, "ontology", None)
        if ontology is None or not doc.line_items:
            ctx.log("map_ontology:skipped(no ontology or no line items)")
            return doc

        # Pull the configured LLM provider so mapping is description-based (see
        # services.mapping). Falls back to the deterministic ensemble if unavailable.
        llm_provider = None
        if ctx.settings.llm.provider != "stub":
            try:
                llm_provider = ctx.registry.get("llm", ctx.settings.llm.provider)
            except Exception as exc:  # unknown/misconfigured provider → deterministic
                ctx.log(f"map_ontology:llm_unavailable({exc})")

        matcher = OntologyMatcher(ontology, locale=doc.locale, settings=ctx.settings,
                                  llm_provider=llm_provider)
        scope = ctx.settings.extraction.mapping_scope
        ctx.log(f"map_ontology:strategy={'llm_description' if matcher.llm_enabled else 'deterministic'}"
                f" scope={scope}")

        def _apply(li, result) -> bool:
            if result and result.canonical_key:
                li.canonical_key = result.canonical_key
                li.confidence.mapping = result.confidence
                li.confidence.method = result.method.value
                if result.allocation_status:
                    li.confidence.flags.append(f"alloc:{result.allocation_status}")
                if result.needs_review:
                    li.confidence.flags.append("low_mapping_confidence")
                return True
            return False

        # Page -> statement, from the classifier. Mapping uses it to refuse concepts from a
        # different statement (a P&L caption resolving to a cash-flow key, etc.).
        stmt_by_page = {p.index: p.statement for p in doc.pages if p.statement}

        def _statement_of(li) -> str | None:
            for ev in li.values.values():
                if ev.provenance is not None:
                    return stmt_by_page.get(ev.provenance.page_index)
            return None

        mapped = 0
        if scope == "per_statement":
            # One grounded LLM call per statement — grouped by source sheet/page so
            # cross-line context (containment, residual, "Others") is available.
            by_group: dict[int, list] = {}
            for li in doc.line_items:
                pg = next((ev.provenance.page_index for ev in li.values.values()
                           if ev.provenance is not None), 0)
                by_group.setdefault(pg, []).append(li)
            by_id = {str(li.id): li for li in doc.line_items}
            for group in by_group.values():
                results = matcher.match_batch([(str(li.id), li.source_label) for li in group],
                                              statement=_statement_of(group[0]))
                for iid, res in results.items():
                    if _apply(by_id[iid], res):
                        mapped += 1
        else:
            for li in doc.line_items:
                if _apply(li, matcher.match(li.source_label, statement=_statement_of(li))):
                    mapped += 1

        # Roll the mapper's LLM usage up onto the context for the audit log.
        ctx.llm_input_tokens += matcher.usage["input_tokens"]
        ctx.llm_output_tokens += matcher.usage["output_tokens"]
        ctx.llm_calls += matcher.usage["calls"]
        if matcher.usage["model"]:
            ctx.llm_model = matcher.usage["model"]
        ctx.log(f"map_ontology:mapped={mapped}/{len(doc.line_items)} llm_calls={matcher.usage['calls']}")
        return doc
