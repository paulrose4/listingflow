"""Local, revisioned ListingFlow workbench. No model API or network access."""

import argparse
import copy
import importlib.metadata
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

from lf_io import SUPPORTED, render_pdf, sha
from lf_excel import write_pair, verify_pair
from lf_rules import (build_checks, compile_bundle, content_blocks, digest, validate_bundle,
                      validate_content, validate_review)
from lf_quality import (active as editorial_active, apply_changes, brief_template, evidence_for_fact,
                        generation_context, review_template, validate_brief)
from lf_experience import dashboard

SKILL = Path(__file__).resolve().parent.parent
SCHEMA = 1


def now():
    return datetime.now(timezone.utc).isoformat()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Invalid JSON: {x}")))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path outside authorized scope: {path}")
    return path


@contextmanager
def connect(task):
    task = Path(task).resolve()
    if not (task / "task.sqlite3").is_file():
        raise ValueError("Task database missing; use init")
    db = sqlite3.connect(task / "task.sqlite3", timeout=5)
    db.execute("PRAGMA busy_timeout=5000")
    try:
        with db:
            yield db
    finally:
        db.close()


def current(task):
    with connect(task) as db:
        row = db.execute("SELECT revision, body FROM revisions ORDER BY revision DESC LIMIT 1").fetchone()
    state = json.loads(row[1])
    if state.get("schema") != SCHEMA:
        raise ValueError("Task schema incompatible; do not overwrite")
    if state.get("workflow_version", 1) not in {1, 2, 3}:
        raise ValueError("Task workflow version incompatible; do not overwrite")
    state["revision"] = row[0]
    return state


def commit(task, expect, kind, state):
    state = copy.deepcopy(state)
    state.pop("revision", None)
    with connect(task) as db:
        db.execute("BEGIN IMMEDIATE")
        latest = db.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
        if latest != expect:
            raise ValueError(f"Revision conflict: expected {expect}, current {latest}; reload before retry")
        db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?)",
                   (latest + 1, now(), kind, json.dumps(state, ensure_ascii=False, allow_nan=False)))
    return {"task": str(Path(task).resolve()), "revision": latest + 1, "operation": kind}


def integrity(task, state):
    errors = []
    for source in state["sources"]:
        if source.get("snapshot"):
            path = inside(Path(task) / source["snapshot"], task)
            if not path.is_file() or sha(path) != source["sha256"]:
                errors.append(source["id"] + ": snapshot missing or modified")
        for unit in source.get("units", []):
            if unit.get("visual_path"):
                path = inside(unit["visual_path"], task)
                if not path.is_file() or sha(path) != unit["sha256"]:
                    errors.append(unit["id"] + ": derived image missing or modified")
    if digest(state["bundle"]) != state["bundle_hash"]:
        errors.append("Rule bundle hash mismatch")
    if state.get("facts") and digest(state["facts"]) != state["facts_hash"]:
        errors.append("Frozen fact hash mismatch")
    if state.get("research") and digest(state["research"]) != state.get("research_hash"):
        errors.append("Keyword research hash mismatch")
    if editorial_active(state):
        if digest(state.get("editorial")) != state.get("editorial_hash"):
            errors.append("Editorial resource hash mismatch")
        if state.get("brief") and digest(state["brief"]) != state.get("brief_hash"):
            errors.append("Writing brief hash mismatch")
    for record in state["contents"]:
        if digest(record["content"]) != record["hash"]:
            errors.append(f"Content v{record['version']} hash mismatch")
        if record.get("brief") and digest(record["brief"]) != record.get("brief_hash"):
            errors.append(f"Content v{record['version']} brief snapshot hash mismatch")
        if record.get("research") and digest(record["research"]) != record.get("research_hash"):
            errors.append(f"Content v{record['version']} research snapshot hash mismatch")
    if errors:
        raise ValueError("; ".join(errors))


def source_units(state):
    return {u["id"]: (s, u) for s in state["sources"] for u in s.get("units", [])}


def init(args):
    if not args.sku or args.sku != args.sku.strip():
        raise ValueError("SKU must be nonempty and preserved exactly, without surrounding whitespace")
    root = Path(args.root).expanduser().resolve()
    if root.is_relative_to(SKILL):
        raise ValueError("Runtime data must not be stored inside the skill")
    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError("Authorized source root must be an existing directory")
    bundle = validate_bundle(load(args.bundle or SKILL / "assets" / "bundle.json"))
    if args.language not in bundle["policy"]["sites"].get(args.site, []):
        raise ValueError("Site/language pair not supported by selected bundle")
    task = root / ("LF-" + datetime.now().strftime("%Y%m%d-") + uuid.uuid4().hex[:10])
    if task.is_relative_to(source_root):
        raise ValueError("Output task directory must be outside the authorized source tree")
    task.mkdir(parents=True, exist_ok=False)
    state = {"schema": SCHEMA, "id": task.name, "created": now(), "sku": args.sku, "site": args.site,
             "language": args.language, "category": args.category, "source_root": str(source_root),
             "parent_task": args.parent_task, "sources": [], "facts": None, "contents": [],
             "bundle": bundle, "bundle_hash": digest(bundle)}
    state.update(workflow_version=3, checklist_version=1, research_version=1,
                 editorial=load(SKILL / "assets/editorial.json"))
    state["editorial_hash"] = digest(state["editorial"])
    with closing(sqlite3.connect(task / "task.sqlite3")) as db, db:
        db.execute("CREATE TABLE revisions (revision INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)")
        db.execute("INSERT INTO revisions VALUES (0, ?, 'init', ?)", (now(), json.dumps(state, ensure_ascii=False)))
    return {"task": str(task), "revision": 0, "rule_status": bundle["status"]}


def doctor(args):
    packages = {}
    for package, module in (("openpyxl", "openpyxl"), ("python-docx", "docx"),
                            ("pypdf", "pypdf"), ("Pillow", "PIL"), ("pypdfium2", "pypdfium2")):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = "MISSING"
    node = args.node or os.environ.get("LISTINGFLOW_NODE") or shutil.which("node")
    export_probe = None
    if node:
        try:
            probe = subprocess.run([node, str(SKILL / "scripts" / "export.mjs"), "--probe"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=45)
            export_probe = {"ok": probe.returncode == 0, "detail": (probe.stdout or probe.stderr)[-1500:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            export_probe = {"ok": False, "detail": str(exc)}
    return {"python": sys.executable, "python_version": sys.version.split()[0], "packages": packages,
            "node": node, "optional_preview": export_probe, "excel_engine": "openpyxl",
            "bundle_present": (SKILL / "assets/bundle.json").is_file(),
            "scope": "Local interactive workflow. No cloud/store login, API costs, or authenticated reviewers."}


def enumerate_paths(paths, source_root, cap):
    found = {}

    def visit(path):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            found[str(path.absolute())] = ("excluded", "Symlink/junction not followed")
            return
        p = inside(path, source_root)
        if len(found) >= cap:
            raise ValueError("File inventory limit exceeded; select narrower paths (nothing committed)")
        if p.is_dir():
            for child in sorted(p.iterdir(), key=lambda x: x.name.casefold()):
                visit(child)
        elif p.is_file():
            found[str(p)] = (None, None)
        else:
            raise ValueError(f"Source path missing: {p}")

    for path in paths:
        visit(Path(path))
    return found


def ingest(args, state):
    if state["facts"]:
        raise ValueError("Facts frozen; create a new task to refresh sources")
    limits = state["bundle"]["policy"]["limits_runtime"]
    selected = enumerate_paths(args.path, state["source_root"], limits["files"])
    previous = {s["original"] for s in state["sources"]}
    if len(previous | set(selected)) > limits["files"]:
        raise ValueError("Total task inventory limit exceeded")
    total = sum(s.get("bytes", 0) for s in state["sources"] if s.get("snapshot"))
    task = Path(args.task).resolve()
    for original, (preset, reason) in selected.items():
        if original in previous:
            prior = next(s for s in state["sources"] if s["original"] == original)
            if prior.get("snapshot") and sha(original) != prior["sha256"]:
                raise ValueError("Previously ingested source changed; create a new task for refreshed input")
            continue
        path = Path(original)
        sid = f"S{len(state['sources']) + 1:04}"
        source = {"id": sid, "original": original, "name": path.name, "units": [], "gaps": [],
                  "status": preset, "bytes": path.stat().st_size if not preset else 0}
        if not preset and (path.name.startswith("~$") or source["bytes"] == 0):
            preset, reason = "excluded", "Office temporary or zero-byte file"
        if not preset and path.suffix.lower() not in SUPPORTED:
            preset, reason = "unsupported", "Format outside first-release support"
        if not preset and (source["bytes"] > limits["file_bytes"] or total + source["bytes"] > limits["total_bytes"]):
            preset, reason = "over_limit", "File or total byte limit exceeded"
        if preset:
            source.update(status=preset, gaps=[{"id": sid + ":G1", "locator": "file", "reason": reason}])
            state["sources"].append(source)
            continue
        snapshot_dir = task / "snapshots"
        snapshot_dir.mkdir(exist_ok=True)
        before = sha(path)
        snapshot = snapshot_dir / (before + path.suffix.lower())
        if not snapshot.exists():
            with path.open("rb") as src, snapshot.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        if sha(snapshot) != before or sha(path) != before:
            raise ValueError("Source changed during ingestion; select a stable copy and retry")
        total += source["bytes"]
        source.update(sha256=before, snapshot=str(snapshot.relative_to(task)))
        with tempfile.TemporaryDirectory(prefix="parse-", dir=task) as temp:
            request, response = Path(temp) / "request.json", Path(temp) / "response.json"
            write_new(request, {"path": str(snapshot), "target": str(task / "derived" / sid), "limits": limits})
            try:
                run = subprocess.run([sys.executable, "-X", "utf8", str(SKILL / "scripts/lf_io.py"),
                                      str(request), str(response)], capture_output=True, timeout=limits["parse_seconds"])
                parsed = load(response) if response.exists() and run.returncode == 0 else {
                    "status": "FAILED", "units": [], "gaps": [{"locator": "file", "reason": "Parser process failed"}]}
            except subprocess.TimeoutExpired:
                parsed = {"status": "FAILED", "units": [], "gaps": [{"locator": "file", "reason": "Parser time limit exceeded"}]}
        source.update(parsed)
        for i, unit in enumerate(source["units"], 1):
            unit["id"] = f"{sid}:U{i}"
        for i, gap in enumerate(source["gaps"], 1):
            gap["id"] = f"{sid}:G{i}"
        state["sources"].append(source)
    return commit(args.task, args.expect, "ingest", state)


def freeze_facts(payload, state):
    if not state["sources"]:
        raise ValueError("No sources ingested")
    if payload.get("sku") != state["sku"] or payload.get("site") != state["site"]:
        raise ValueError("Facts must match exact SKU/site")
    if not isinstance(payload.get("product_revision"), str) or not payload["product_revision"].strip():
        raise ValueError("Explicit product revision/batch identification required")
    choices = payload.get("selection", {})
    if set(choices) != {s["id"] for s in state["sources"]}:
        raise ValueError("Every source requires use/exclude decision")
    for source in state["sources"]:
        choice = choices[source["id"]]
        if choice.get("action") not in {"use", "exclude"} or not choice.get("reason"):
            raise ValueError("Source selection requires action and reason")
        if choice["action"] == "use":
            if source["status"] not in {"SUCCESS", "PARTIAL"}:
                raise ValueError("Cannot use unread/unsupported source")
            if choice.get("sku") != state["sku"] or choice.get("site") != state["site"]:
                raise ValueError("Used source must have explicit target applicability")
    coverage = payload.get("coverage", {})
    gaps = {g["id"]: (s, g) for s in state["sources"] for g in s["gaps"]
            if choices[s["id"]]["action"] == "use"}
    if set(coverage) != set(gaps):
        raise ValueError("Each gap in used sources needs an explicit coverage disposition")
    units = source_units(state)
    for gid, item in coverage.items():
        if item.get("action") not in {"inspected", "exclude"} or not item.get("reason"):
            raise ValueError("Coverage requires inspected/exclude with rationale")
        if item["action"] == "inspected":
            evidence = item.get("observation_ids", [])
            observations = {o["id"]: o for o in state.get("observations", [])}
            if not evidence or any(i not in observations for i in evidence):
                raise ValueError("Inspected coverage requires recorded observations")
            sid = gaps[gid][0]["id"]
            loc = gaps[gid][1]["locator"]
            if not any(observations[i]["unit_id"] in units
                       and units[observations[i]["unit_id"]][0]["id"] == sid
                       and units[observations[i]["unit_id"]][1]["locator"] == loc for i in evidence):
                raise ValueError("Observation must address the same source and locator as the gap")
    if payload.get("unresolved"):
        raise ValueError("Unresolved essential facts/conflicts; ask the user before freezing")
    facts = payload.get("facts", [])
    ids = set()
    for fact in facts:
        if not fact.get("id") or fact["id"] in ids:
            raise ValueError("Facts need unique IDs")
        ids.add(fact["id"])
        if fact.get("sku") != state["sku"] or fact.get("status") != "confirmed":
            raise ValueError("Only explicitly applicable confirmed facts may be frozen")
        if not fact.get("field") or not isinstance(fact.get("value"), str) or not fact["value"].strip():
            raise ValueError("Fact field/value required")
        if not fact.get("sources") or any(i not in units for i in fact["sources"]):
            raise ValueError("Fact source IDs must exist")
        if any(choices[units[i][0]["id"]]["action"] != "use" for i in fact["sources"]):
            raise ValueError("Fact cites an excluded source")
        if not fact.get("support_reason"):
            raise ValueError("Record why evidence supports each fact, not just an ID")
    required = set(state["bundle"]["policy"]["required_fact_fields"]) | set(payload.get("required_fields", []))
    if not required.issubset({f["field"] for f in facts}):
        raise ValueError(f"Missing minimum fact fields: {sorted(required - {f['field'] for f in facts})}")
    # Multiple conflicting values for one field must be resolved before freezing.
    values = {}
    for fact in facts:
        values.setdefault(fact["field"], set()).add(fact["value"])
    if any(len(v) > 1 for v in values.values()):
        raise ValueError("Conflicting values for one fact field; resolve or use explicit distinct fields")
    for decision in payload.get("decisions", []):
        if not all(decision.get(k) for k in ("question", "answer", "actor", "quote")):
            raise ValueError("Human decisions require question, answer, actor and actual quote")
    from lf_reliability import validate_facts
    validate_facts(payload, state)
    return payload


def observe(args, state):
    if state["facts"]:
        raise ValueError("Observations frozen; use new task for new evidence")
    item = load(args.json)
    if item.get("unit_id") not in source_units(state):
        raise ValueError("Observation source unit missing")
    if item.get("method") not in {"visual", "operator_statement", "formula_verification"}:
        raise ValueError("Unknown observation method")
    if not all(item.get(k) for k in ("text", "actor", "reason")):
        raise ValueError("Observation requires actual text, actor and reason")
    if item["method"] == "operator_statement" and not item.get("quote"):
        raise ValueError("Operator statement requires actual quote")
    item.update(id=f"O{len(state.get('observations', [])) + 1}", created=now())
    state.setdefault("observations", []).append(item)
    return commit(args.task, args.expect, "observe", state)


def statement(args, state):
    if state["facts"]:
        raise ValueError("Facts frozen; use a new task for new factual statements")
    if not any(s.get("snapshot") for s in state["sources"]):
        raise ValueError("Import the product materials before supplementing them with a statement")
    item = load(args.json)
    if not all(isinstance(item.get(k), str) and item[k].strip() for k in ("text", "actor", "quote", "reason")):
        raise ValueError("Statement requires text, actor, actual user quote and reason")
    sid = f"S{len(state['sources']) + 1:04}"
    state["sources"].append({
        "id": sid, "original": "operator-statement:" + uuid.uuid4().hex,
        "name": "人工补充说明", "status": "SUCCESS", "bytes": 0, "gaps": [],
        "created": now(), "actor": item["actor"], "quote": item["quote"], "reason": item["reason"],
        "units": [{"id": sid + ":U1", "locator": "operator-statement", "text": item["text"],
                   "kind": "operator_statement", "actor": item["actor"], "quote": item["quote"]}]})
    result = commit(args.task, args.expect, "statement", state)
    result["source_id"] = sid
    return result


def save_content(args, state, replacement=None):
    if not state["facts"]:
        raise ValueError("Freeze sufficient facts before writing content")
    content = load(args.json) if replacement is None else replacement
    new = validate_content(content, state["facts"])
    if editorial_active(state) and not state.get("brief"):
        raise ValueError("Prepare and save the evidence-based writing brief before content")
    from lf_research import require_current
    require_current(state, state.get("brief"))
    if state["contents"]:
        previous = dict(content_blocks(state["contents"][-1]["content"]))
        previous["keywords"] = state["contents"][-1]["content"]["keywords"]
        proposed = {**new, "keywords": content["keywords"]}
        for locked in state.get("locked_blocks", []):
            if previous.get(locked) != proposed.get(locked):
                raise ValueError(f"Operator-locked block cannot be changed: {locked}; obtain explicit unlock")
    if getattr(args, "only", None):
        if not state["contents"]:
            raise ValueError("Partial rewrite requires an existing content baseline")
        old = dict(content_blocks(state["contents"][-1]["content"]))
        allowed = set(args.only)
        if not allowed.issubset(set(old) | {"keywords"}):
            raise ValueError("Unknown partial rewrite path")
        if set(old) != set(new):
            raise ValueError("Partial rewrite cannot add/remove blocks")
        for key in old:
            if key not in allowed and old[key] != new[key]:
                raise ValueError(f"Unselected block changed: {key}")
        if "keywords" not in allowed and state["contents"][-1]["content"]["keywords"] != content["keywords"]:
            raise ValueError("Unselected keywords changed")
    if (editorial_active(state) and state["contents"] and state["contents"][-1]["content"] == content
            and state["contents"][-1].get("brief_hash") == state.get("brief_hash")):
        record = state["contents"][-1]
        return {"task": str(Path(args.task).resolve()), "revision": state["revision"], "operation": args.command,
                "unchanged": True, "content_version": record["version"], "content_hash": record["hash"],
                "changed_paths": [], "blocking_count": build_checks(state, record)["blocking_count"]}
    record = {"version": len(state["contents"]) + 1, "created": now(), "content": content,
              "hash": digest(content), "facts_hash": state["facts_hash"], "review": None, "approval": None}
    if editorial_active(state):
        record.update(brief=copy.deepcopy(state["brief"]), brief_hash=state["brief_hash"])
    if state.get("research_version"):
        record.update(research=copy.deepcopy(state["research"]), research_hash=state["research_hash"])
    before = dict(content_blocks(state["contents"][-1]["content"])) if state["contents"] else {}
    if state["contents"]:
        before["keywords"] = state["contents"][-1]["content"]["keywords"]
    after = {**new, "keywords": content["keywords"]}
    record["changed_paths"] = [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
    record["checks"] = build_checks(state, record)
    state["contents"].append(record)
    result = commit(args.task, args.expect, args.command, state)
    result.update(content_version=record["version"], content_hash=record["hash"],
                  blocking_count=record["checks"]["blocking_count"])
    result["changed_paths"] = record["changed_paths"]
    return result


def latest(state):
    if not state["contents"]:
        raise ValueError("No content version")
    return state["contents"][-1]


def export(args, state):
    record = latest(state)
    checks = build_checks(state, record)
    if args.mode == "final" and (not checks["ready_for_human_approval"]
                               or not record.get("approval")
                               or record["approval"]["content_hash"] != record["hash"]
                               or record["approval"]["checks_hash"] != digest(checks)):
        raise ValueError("Final export blocked: current checks and explicit human approval required; draft is available")
    node = args.node or os.environ.get("LISTINGFLOW_NODE") or shutil.which("node")
    task = Path(args.task).resolve()
    batch = uuid.uuid4().hex[:12]
    pending = task / "exports" / (".pending-" + batch)
    pending.mkdir(parents=True)
    request = {"batch": batch, "mode": args.mode, "created": now(), "generated": record["created"],
               "sku": state["sku"], "site": state["site"],
               "language": state["language"], "version": record["version"], "content_hash": record["hash"],
               "bundle_hash": state["bundle_hash"], "facts_hash": state["facts_hash"],
               "content": record["content"], "checks": checks, "facts": state["facts"],
               "observations": state.get("observations", []),
               "sources": [{"id": s["id"], "name": s["name"], "sha256": s.get("sha256"),
                            "status": s["status"], "gaps": s["gaps"],
                            "units": [{"id": u["id"], "locator": u["locator"], "text": u["text"]}
                                      for u in s["units"]]} for s in state["sources"]]}
    if editorial_active(state):
        request.update(workflow_version=state["workflow_version"], editorial_hash=state["editorial_hash"],
                       brief_hash=record["brief_hash"], operator=dashboard(state, checks),
                       review=record.get("review"))
    from lf_checklist import active as checklist_active
    if checklist_active(state, record):
        request.update(report_layout="operator-overview-v1", rule_catalog=state["bundle"]["rules"],
                       checked_at=now(), approval=record.get("approval"))
    if state.get("research_version"):
        request.update(research_version=1, research=record.get("research"),
                       research_hash=record.get("research_hash"))
    write_new(pending / "export.json", request)
    write_pair(request, pending)
    preview_status = {"requested": args.preview, "status": "not_requested"}
    if args.preview and node:
        try:
            run = subprocess.run([node, str(SKILL / "scripts/export.mjs"), str(pending)],
                                 capture_output=True, text=True, encoding="utf-8", timeout=180)
            preview_status.update(status="generated" if run.returncode == 0 else "runtime_warning",
                                  returncode=run.returncode, detail=(run.stderr or run.stdout)[-1200:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            preview_status.update(status="unavailable", reason=str(exc))
    elif args.preview:
        preview_status.update(status="unavailable", reason="Node not configured; Excel files unaffected")
    verify_pair(request, pending)
    final = pending.with_name(batch)
    paths = [str(final / name) for name in ("文案.xlsx", "自查.xlsx")]
    state.setdefault("exports", []).append({"batch": batch, "mode": args.mode, "version": record["version"],
                                           "content_hash": record["hash"], "paths": paths, "created": now(),
                                           "preview": preview_status,
                                           "sha256": {n: sha(pending / n) for n in ("文案.xlsx", "自查.xlsx")}})
    # Rename and revision commit under one writer lock. A crash can leave an orphan batch,
    # but cannot record a successful export before both files exist.
    with connect(task) as db:
        db.execute("BEGIN IMMEDIATE")
        rev = db.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
        if rev != args.expect:
            raise ValueError("Revision conflict during export; generated pending batch not committed")
        pending.rename(final)
        state.pop("revision", None)
        db.execute("INSERT INTO revisions VALUES (?, ?, 'export', ?)",
                   (rev + 1, now(), json.dumps(state, ensure_ascii=False)))
    return {"revision": rev + 1, "mode": args.mode, "batch": batch, "files": paths, "preview": preview_status}


def run(args):
    if args.command == "doctor":
        return doctor(args)
    if args.command == "init":
        return init(args)
    if args.command == "tasks":
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir() or not 1 <= args.limit <= 100:
            raise ValueError("Existing authorized task root and limit 1..100 required")
        candidates = sorted((p for p in root.glob("LF-*") if p.is_dir() and not p.is_symlink()
                             and not p.is_junction() and (p / "task.sqlite3").is_file()),
                            key=lambda p: (p / "task.sqlite3").stat().st_mtime, reverse=True)
        found, errors = [], []
        for path in candidates[:500]:
            try:
                state = current(inside(path, root))
                if args.sku is None or state["sku"] == args.sku:
                    found.append({"task": str(path), "id": state["id"], "sku": state["sku"], "site": state["site"],
                                  "language": state["language"], "revision": state["revision"],
                                  "content_versions": len(state["contents"]), "integrity": "not_checked"})
            except (ValueError, KeyError, sqlite3.Error, json.JSONDecodeError) as exc:
                errors.append({"task": str(path), "reason": str(exc)})
        return {"tasks": found[:args.limit], "more": len(found) > args.limit,
                "scan_complete": len(candidates) <= 500, "errors": errors,
                "note": "列表只读取任务摘要；选定任务后用 dashboard/status 核验快照。"}
    if args.command == "compile-bundle":
        bundle = compile_bundle(args.source_root, load(SKILL / "assets/policy.json"))
        validate_bundle(bundle)
        write_new(args.output, bundle)
        return {"output": str(Path(args.output).resolve()), "rules": len(bundle["rules"]),
                "quarantine": len(bundle["quarantine"]), "status": bundle["status"]}
    if args.command == "publish-bundle":
        bundle = validate_bundle(load(args.json))
        if bundle["status"] != "approved":
            raise ValueError("Publication requires explicit approved bundle and recorded decisions")
        base = load(args.base or SKILL / "assets/bundle.json")
        before, after = ({r["id"]: r for r in data["rules"]} for data in (base, bundle))
        if set(before) != set(after) or bundle["sources"] != base["sources"]:
            raise ValueError("Publication cannot silently delete source rules or change provenance")
        for key in before:
            if any(before[key].get(field) != after[key].get(field) for field in ("raw", "sources", "group")):
                raise ValueError(f"Preserve original rule provenance: {key}")
        if {q["id"] for q in base["quarantine"]} != {q["id"] for q in bundle["quarantine"]}:
            raise ValueError("Quarantine entries must be resolved, not deleted")
        if bundle["policy"]["version"] == base["policy"]["version"]:
            raise ValueError("Published bundle needs a new policy version")
        write_new(args.output, bundle)
        return {"output": str(Path(args.output).resolve()), "sha256": digest(bundle)}
    state = current(args.task)
    integrity(args.task, state)
    if hasattr(args, "expect") and state["revision"] != args.expect:
        raise ValueError(f"Revision conflict: current {state['revision']}, expected {args.expect}")
    if args.command == "status":
        return {"task": str(Path(args.task).resolve()), "revision": state["revision"], "sku": state["sku"],
                "site": state["site"], "language": state["language"], "sources": [
                    {"id": s["id"], "name": s["name"], "status": s["status"], "units": len(s["units"]),
                     "gaps": len(s["gaps"])} for s in state["sources"]],
                "facts_frozen": bool(state["facts"]), "content_versions": len(state["contents"]),
                "bundle_status": state["bundle"]["status"],
                "latest_checks": state["contents"][-1]["checks"] if state["contents"] and args.details else None,
                "exports": state.get("exports", []), "integrity": "verified"}
    if args.command == "dashboard":
        return dashboard(state, build_checks(state, latest(state)) if state["contents"] else None)
    if args.command == "context":
        return generation_context(state)
    if args.command == "evidence":
        return evidence_for_fact(state, args.fact)
    if args.command == "prepare":
        from lf_research import template as research_template
        payload = (research_template(state) if args.kind == "research" else
                   brief_template(state) if args.kind == "brief" else review_template(state))
        dest = inside(Path(args.task) / "inputs" / f"{args.kind}-r{state['revision']}-{uuid.uuid4().hex[:8]}.json", args.task)
        write_new(dest, payload)
        return {"template": str(dest), "revision": state["revision"], "status": "尚未填写，不代表审核通过"}
    if args.command == "history":
        with connect(args.task) as db:
            return [{"revision": r, "time": t, "operation": k}
                    for r, t, k in db.execute("SELECT revision, created, kind FROM revisions ORDER BY revision")]
    if args.command == "show":
        if args.section == "content":
            return latest(state)
        if args.section == "checks":
            return build_checks(state, latest(state))
        return state.get(args.section)
    if args.command == "query":
        if args.offset < 0 or not 1 <= args.limit <= 1000:
            raise ValueError("Query offset must be nonnegative; limit must be 1..1000")
        units = source_units(state)
        selected = [{"source": sid, **unit} for sid, (_, unit) in units.items()
                    if (not args.source or sid.split(":")[0] == args.source)
                    and (not args.text or args.text.casefold() in (unit["text"] + " " + unit["locator"]).casefold())]
        return {"total_matches": len(selected), "offset": args.offset, "returned": len(selected[args.offset:args.offset + args.limit]),
                "has_more": len(selected) > args.offset + args.limit, "units": selected[args.offset:args.offset + args.limit]}
    if args.command == "compare":
        if min(args.first, args.second) < 1 or max(args.first, args.second) > len(state["contents"]):
            raise ValueError("Content version does not exist")
        a, b = (state["contents"][v - 1] for v in (args.first, args.second))
        aa, bb = dict(content_blocks(a["content"])), dict(content_blocks(b["content"]))
        aa["keywords"], bb["keywords"] = a["content"]["keywords"], b["content"]["keywords"]
        return {"first": args.first, "second": args.second,
                "changes": [{"path": k, "before": aa.get(k), "after": bb.get(k)}
                            for k in sorted(set(aa) | set(bb)) if aa.get(k) != bb.get(k)]}
    if args.command == "render":
        sources = {s["id"]: s for s in state["sources"]}
        source = sources[args.source]
        if not source.get("snapshot") or Path(source["snapshot"]).suffix != ".pdf":
            raise ValueError("render requires an ingested PDF")
        dest = Path(args.task).resolve() / "previews" / f"{args.source}-page{args.page}.png"
        dest.parent.mkdir(exist_ok=True)
        render_pdf(inside(Path(args.task) / source["snapshot"], args.task), args.page, dest)
        return {"page": args.page, "preview": str(dest), "note": "Rendering is not inspection; record observation after viewing"}
    if args.command == "ingest":
        return ingest(args, state)
    if args.command == "observe":
        return observe(args, state)
    if args.command == "statement":
        return statement(args, state)
    if args.command == "research":
        from lf_research import validate as validate_research
        if not state.get("research_version"):
            raise ValueError("Legacy tasks retain their workflow; create a new task for keyword research")
        research = validate_research(load(args.json), state)
        if state.get("research") == research:
            return {"revision": state["revision"], "unchanged": True, "research_hash": state["research_hash"]}
        state.update(research=research, research_hash=digest(research))
        if state["contents"]:
            latest(state)["approval"] = None
            latest(state)["checks"] = build_checks(state, latest(state))
    elif args.command == "brief":
        brief = validate_brief(load(args.json), state)
        if state.get("brief") == brief:
            return {"task": str(Path(args.task).resolve()), "revision": state["revision"],
                    "operation": "brief", "unchanged": True, "brief_hash": state["brief_hash"]}
        state["brief"] = brief
        state["brief_hash"] = digest(state["brief"])
        if state["contents"]:
            latest(state)["approval"] = None
            latest(state)["checks"] = build_checks(state, latest(state))
    elif args.command == "revise":
        changes = load(args.json)
        content = apply_changes(latest(state)["content"], changes)
        args.only = list(changes)
        return save_content(args, state, content)
    elif args.command == "lock":
        item = load(args.json)
        if item.get("action") not in {"lock", "unlock"} or not all(item.get(k) for k in ("actor", "quote")):
            raise ValueError("Block lock/unlock requires explicit user intent and actual quote")
        paths = item.get("paths")
        allowed = set(dict(content_blocks(latest(state)["content"]))) | {"keywords"}
        if not isinstance(paths, list) or not paths or any(p not in allowed for p in paths):
            raise ValueError("Lock paths must reference existing content blocks")
        locked = set(state.get("locked_blocks", []))
        state["locked_blocks"] = sorted(locked | set(paths) if item["action"] == "lock" else locked - set(paths))
        state.setdefault("lock_decisions", []).append({**item, "created": now()})
    elif args.command == "freeze":
        if state["facts"]:
            raise ValueError("Facts already frozen; use new task")
        state["facts"] = freeze_facts(load(args.json), state)
        state["facts_hash"] = digest(state["facts"])
    elif args.command == "save-content":
        return save_content(args, state)
    elif args.command == "review":
        record = latest(state)
        record["review"] = validate_review(load(args.json), state, record)
        if state.get("workflow_version", 1) >= 3 and "operator_checklist" in record["review"]:
            state["checklist_version"] = 1
        record["review"]["created"] = now()
        record["approval"] = None
        record["checks"] = build_checks(state, record)
    elif args.command == "check":
        record = latest(state)
        record["checks"] = build_checks(state, record)
        if record.get("approval") and record["approval"]["checks_hash"] != digest(record["checks"]):
            record["approval"] = None
    elif args.command == "approve":
        record = latest(state)
        checks = build_checks(state, record)
        if not checks["ready_for_human_approval"]:
            raise ValueError("Blocking checks remain; approval cannot override them")
        approval = load(args.json)
        if approval.get("content_hash") != record["hash"] or not all(approval.get(k) for k in ("actor", "quote")):
            raise ValueError("Approval requires exact content hash, actual user quote and actor")
        approval.update(created=now(), checks_hash=digest(checks))
        record.update(approval=approval, checks=checks)
    elif args.command == "export":
        return export(args, state)
    else:
        raise ValueError("Unknown command")
    result = commit(args.task, args.expect, args.command, state)
    if state["contents"]:
        result["blocking_count"] = latest(state)["checks"]["blocking_count"]
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    doc = sub.add_parser("doctor")
    doc.add_argument("--node")
    ini = sub.add_parser("init")
    for key in ("root", "source-root", "sku", "site", "language"):
        ini.add_argument("--" + key, required=True)
    for key in ("category", "bundle", "parent-task"):
        ini.add_argument("--" + key)
    compile_parser = sub.add_parser("compile-bundle")
    compile_parser.add_argument("--source-root", required=True)
    compile_parser.add_argument("--output", required=True)
    pub = sub.add_parser("publish-bundle")
    pub.add_argument("--json", required=True)
    pub.add_argument("--output", required=True)
    pub.add_argument("--base")
    tasks = sub.add_parser("tasks")
    tasks.add_argument("--root", required=True)
    tasks.add_argument("--sku")
    tasks.add_argument("--limit", type=int, default=20)
    for command in ("status", "history", "show", "query", "compare", "render", "ingest", "observe", "statement",
                    "freeze", "save-content", "review", "check", "approve", "export", "brief", "revise",
                    "dashboard", "context", "evidence", "prepare", "lock", "research"):
        c = sub.add_parser(command)
        c.add_argument("--task", required=True)
        if command in {"ingest", "observe", "statement", "freeze", "save-content", "review", "check", "approve", "export",
                       "brief", "revise", "prepare", "lock", "research"}:
            c.add_argument("--expect", type=int, required=True)
        if command in {"observe", "statement", "freeze", "save-content", "review", "approve", "brief", "revise", "lock", "research"}:
            c.add_argument("--json", required=True)
        if command == "ingest":
            c.add_argument("--path", action="append", required=True)
        elif command == "save-content":
            c.add_argument("--only", action="append")
        elif command == "status":
            c.add_argument("--details", action="store_true")
        elif command == "show":
            c.add_argument("--section", choices=["sources", "facts", "content", "checks", "bundle", "observations",
                                                "brief", "locked_blocks", "research"], required=True)
        elif command == "query":
            c.add_argument("--text")
            c.add_argument("--source")
            c.add_argument("--offset", type=int, default=0)
            c.add_argument("--limit", type=int, default=40)
        elif command == "compare":
            c.add_argument("--first", type=int, required=True)
            c.add_argument("--second", type=int, required=True)
        elif command == "render":
            c.add_argument("--source", required=True)
            c.add_argument("--page", type=int, required=True)
        elif command == "export":
            c.add_argument("--mode", choices=["draft", "final"], default="draft")
            c.add_argument("--node")
            c.add_argument("--preview", action="store_true")
        elif command == "evidence":
            c.add_argument("--fact", required=True)
        elif command == "prepare":
            c.add_argument("--kind", choices=["brief", "review", "research"], required=True)
    return p


if __name__ == "__main__":
    try:
        args = parser().parse_args()
        print(json.dumps({"ok": True, "result": run(args)}, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        sys.exit(1)
