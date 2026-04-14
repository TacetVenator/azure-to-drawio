"""Intent registry for consultant-style local analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


STANDARD_OUTPUT_SECTIONS = [
    "Executive Summary",
    "Known Facts",
    "Inferred Interpretation",
    "Risks / Blockers",
    "Open Questions",
    "Recommended Next Checks",
    "Missing Evidence",
    "Confidence Notes",
    "Evidence References",
]


@dataclass(frozen=True)
class AnalysisIntent:
    name: str
    title: str
    domain: str
    business_goal: str
    audience: List[str]
    specialist_lens: str
    decision_owners: List[str]
    required_evidence: List[str]
    helper_scripts: List[str]
    retrieval_profile: List[str]
    output_sections: List[str]
    review_checklist: List[str]
    expected_gaps: List[str]
    prompt_template: str


_INTENTS = [
    AnalysisIntent(
        name="estate-summary",
        title="Estate Summary",
        domain="current-state",
        business_goal="Explain what is deployed, where it sits, and how complete the evidence appears.",
        audience=["architect", "delivery-lead", "project-manager"],
        specialist_lens="General migration discovery",
        decision_owners=["application", "platform"],
        required_evidence=["pack_fact_sheet", "graph_summary", "policy_summary", "rbac_summary"],
        helper_scripts=["pack_fact_sheet", "summarize_graph", "summarize_policy", "summarize_rbac"],
        retrieval_profile=["facts", "migration-plan", "graph"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Separate direct evidence from inference.",
            "Call out scope boundaries and confidence limits.",
            "Prefer fact sheets over raw JSON interpretation.",
        ],
        expected_gaps=["Detailed workload runtime behavior", "Non-Azure dependencies", "Business criticality context"],
        prompt_template=(
            "Prepare an estate summary for a migration consultant. Explain the deployed Azure estate in concise business language. "
            "Use only the provided evidence. State known facts, inferred interpretation, open questions, confidence notes, and cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="dependency-review",
        title="Dependency Review",
        domain="dependencies",
        business_goal="Identify coupling, shared dependencies, and off-scope relationships that could affect migration planning.",
        audience=["architect", "platform-engineer", "network-engineer"],
        specialist_lens="Application and shared-service dependency analysis",
        decision_owners=["application", "platform", "network"],
        required_evidence=["pack_fact_sheet", "shared_services", "graph_summary", "telemetry_gaps"],
        helper_scripts=["find_shared_services", "summarize_graph", "summarize_telemetry_gaps"],
        retrieval_profile=["facts", "graph", "unresolved", "migration-plan"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Highlight cross-resource-group and cross-subscription coupling.",
            "Distinguish configuration edges from telemetry-derived evidence.",
            "Call out unresolved targets explicitly.",
        ],
        expected_gaps=["Runtime call chains when telemetry is missing", "Third-party integrations not visible in Azure resources"],
        prompt_template=(
            "Review the dependency picture for this migration pack. Identify what must likely move together, what looks shared, "
            "what appears outside scope, and which dependencies remain uncertain. Use the evidence only and cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="exposure-review",
        title="Exposure Review",
        domain="network-security",
        business_goal="Explain public and private exposure patterns and where the evidence is incomplete.",
        audience=["architect", "network-engineer", "security"],
        specialist_lens="Exposure and connectivity posture review",
        decision_owners=["network", "security", "platform"],
        required_evidence=["exposure_summary", "pack_fact_sheet", "policy_summary"],
        helper_scripts=["summarize_exposure", "summarize_policy"],
        retrieval_profile=["facts", "graph", "policy", "migration-plan"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Call out direct public exposure separately from inferred exposure.",
            "Note private endpoints and missing network visibility.",
            "Flag policy signals relevant to exposure.",
        ],
        expected_gaps=["Actual firewall rule effectiveness", "On-prem routing paths", "WAF or reverse proxy behavior outside visible resources"],
        prompt_template=(
            "Review how this workload is exposed. Summarize public entry points, private connectivity indicators, policy or configuration concerns, and missing evidence. "
            "Do not assume traffic paths that are not supported by evidence. Cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="migration-readiness",
        title="Migration Readiness",
        domain="migration-planning",
        business_goal="Review the migration packs and identify blockers, missing assumptions, and sequencing risks.",
        audience=["architect", "delivery-lead", "migration-engineer"],
        specialist_lens="Senior migration consultant workpack review",
        decision_owners=["application", "platform", "security", "operations"],
        required_evidence=["pack_fact_sheet", "shared_services", "exposure_summary", "policy_summary", "telemetry_gaps"],
        helper_scripts=["pack_fact_sheet", "find_shared_services", "summarize_exposure", "summarize_policy", "summarize_telemetry_gaps"],
        retrieval_profile=["migration-plan", "facts", "graph", "policy", "rbac"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Review the generated migration plan, wave plan, and questionnaire against evidence.",
            "Call out hidden dependencies, governance gaps, and rollback risks.",
            "Escalate uncertainty instead of filling gaps with assumptions.",
        ],
        expected_gaps=["Actual runbook readiness", "Cutover rehearsals", "Business blackout periods unless documented"],
        prompt_template=(
            "Act like a senior migration consultant reviewing a junior analyst workpack. Use the migration-plan artifacts plus evidence summaries "
            "to identify missing assumptions, hidden dependencies, governance gaps, and cutover or rollback risks. Cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="target-state-inputs",
        title="Target State Inputs",
        domain="target-state",
        business_goal="Identify the decisions still needed from application, platform, network, security, and operations stakeholders.",
        audience=["architect", "delivery-lead", "platform-engineer"],
        specialist_lens="Decision backlog definition",
        decision_owners=["application", "platform", "network", "security", "operations"],
        required_evidence=["pack_fact_sheet", "shared_services", "exposure_summary", "rbac_summary"],
        helper_scripts=["pack_fact_sheet", "find_shared_services", "summarize_exposure", "summarize_rbac"],
        retrieval_profile=["migration-plan", "facts", "rbac", "graph"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Group decisions by stakeholder area.",
            "Do not invent a target state; frame only what needs confirmation.",
            "Cite the evidence that led to each requested decision.",
        ],
        expected_gaps=["Landing Zone standards not yet ingested", "Application non-functional requirements"],
        prompt_template=(
            "Identify the target-state decisions still required to complete migration planning. Group them by application, platform, network, "
            "security, identity, and operations stakeholders. Use the evidence only and cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="evidence-gaps",
        title="Evidence Gaps",
        domain="assurance",
        business_goal="Explain where current permissions, telemetry, or discovery scope limit confidence.",
        audience=["architect", "security", "delivery-lead"],
        specialist_lens="Discovery assurance and blind-spot review",
        decision_owners=["platform", "security", "operations"],
        required_evidence=["telemetry_gaps", "unresolved_summary", "pack_fact_sheet"],
        helper_scripts=["summarize_telemetry_gaps", "summarize_unresolved", "pack_fact_sheet"],
        retrieval_profile=["facts", "unresolved", "migration-plan", "graph"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Be explicit about missing telemetry, identity visibility, and off-scope dependencies.",
            "Prefer follow-up checks over recommendations that imply certainty.",
            "Do not treat absence of evidence as evidence of absence.",
        ],
        expected_gaps=["Entra permissions", "On-prem evidence", "3rd party SaaS dependencies"],
        prompt_template=(
            "Explain the evidence gaps that limit migration confidence. Focus on missing telemetry, unresolved references, likely scope gaps, "
            "and permissions-related blind spots. Cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="encryption-posture",
        title="Encryption Posture",
        domain="security",
        business_goal="Assess what can currently be said about encryption at rest, encryption in transit, and customer-managed key dependencies.",
        audience=["security", "architect", "platform-engineer"],
        specialist_lens="Cloud security and key management review",
        decision_owners=["security", "platform", "application"],
        required_evidence=["pack_fact_sheet", "policy_summary", "shared_services"],
        helper_scripts=["summarize_policy", "find_shared_services", "pack_fact_sheet", "summarize_encryption_gaps"],
        retrieval_profile=["facts", "policy", "graph", "migration-plan"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Do not claim encryption posture certainty unless direct evidence exists.",
            "Call out likely CMK or Key Vault dependencies when visible.",
            "Separate direct control evidence from inferred risk.",
        ],
        expected_gaps=["Disk encryption settings", "Storage encryption settings", "TLS enforcement settings", "CMK/BYOK implementation detail"],
        prompt_template=(
            "Assess the visible encryption posture for migration planning. Describe what can be stated about encryption at rest, encryption in transit, "
            "and key-management dependencies, and explicitly list what evidence is missing before a Landing Zone move can be signed off. Cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="backup-dr-posture",
        title="Backup And DR Posture",
        domain="resilience",
        business_goal="Assess what is currently visible about backup, recovery, vault usage, and disaster recovery assumptions.",
        audience=["operations", "architect", "platform-engineer"],
        specialist_lens="Backup, restore, and resilience review",
        decision_owners=["operations", "platform", "application"],
        required_evidence=["pack_fact_sheet", "shared_services", "policy_summary"],
        helper_scripts=["find_shared_services", "summarize_policy", "summarize_backup_gaps"],
        retrieval_profile=["facts", "graph", "policy", "migration-plan"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Do not infer backup coverage from resource existence alone.",
            "Call out missing restore evidence and DR design assumptions.",
            "Separate visible vault dependencies from actual policy coverage.",
        ],
        expected_gaps=["Backup policy assignments", "Recovery Services evidence", "Restore testing", "RPO/RTO evidence"],
        prompt_template=(
            "Assess what can currently be said about backup and disaster recovery posture. Focus on visible vault or protection dependencies, recovery assumptions, "
            "and the missing evidence that must be collected before migration planning is complete. Cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="logic-apps-integration",
        title="Logic Apps And Integration",
        domain="integration",
        business_goal="Assess integration-heavy workloads such as Logic Apps, connectors, workflow dependencies, and external endpoints.",
        audience=["integration-engineer", "architect", "application"],
        specialist_lens="Integration platform and workflow dependency review",
        decision_owners=["application", "integration", "security", "network"],
        required_evidence=["pack_fact_sheet", "dependency-review", "evidence-gaps"],
        helper_scripts=["summarize_graph", "summarize_unresolved", "summarize_integration_gaps"],
        retrieval_profile=["facts", "graph", "unresolved", "migration-plan"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Call out where connector configuration is not visible in current evidence.",
            "Highlight external endpoints and secret dependencies.",
            "Do not assume workflow behavior from resource type alone.",
        ],
        expected_gaps=["Connector definitions", "Managed identity usage", "Trigger schedules", "Hybrid/on-prem connections"],
        prompt_template=(
            "Assess integration workload risks with emphasis on Logic Apps and external workflow dependencies. Describe what is visible, what likely matters for migration, "
            "and what evidence is missing before target-state design can proceed. Cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="policy-remediation",
        title="Policy Remediation",
        domain="governance",
        business_goal="Classify visible policy issues into migration blockers, target-platform inheritance items, and remediation candidates.",
        audience=["security", "platform-engineer", "architect"],
        specialist_lens="Governance and compliance remediation planning",
        decision_owners=["security", "platform", "application"],
        required_evidence=["policy_summary", "pack_fact_sheet", "exposure_summary"],
        helper_scripts=["summarize_policy", "summarize_exposure", "pack_fact_sheet"],
        retrieval_profile=["facts", "policy", "migration-plan"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Classify issues instead of listing them flatly.",
            "Separate current-state non-compliance from target-state policy design questions.",
            "Do not promise remediation steps without evidence of root cause.",
        ],
        expected_gaps=["Policy definition detail", "Exemption history", "Landing Zone control ownership model"],
        prompt_template=(
            "Review policy evidence and classify visible issues into likely pre-migration blockers, likely target-platform responsibilities, and application remediation candidates. "
            "Be conservative and cite chunk IDs."
        ),
    ),
    AnalysisIntent(
        name="landing-zone-fit",
        title="Landing Zone Fit",
        domain="target-platform",
        business_goal="Assess how ready the workload appears for placement into a new compliant Landing Zone and what design decisions remain open.",
        audience=["architect", "platform-engineer", "security", "network-engineer"],
        specialist_lens="Landing Zone control and platform fit-gap review",
        decision_owners=["platform", "network", "security", "application", "operations"],
        required_evidence=["pack_fact_sheet", "shared_services", "exposure_summary", "policy_summary", "evidence_gaps"],
        helper_scripts=["find_shared_services", "summarize_exposure", "summarize_policy", "pack_fact_sheet", "summarize_landing_zone_gaps"],
        retrieval_profile=["facts", "graph", "policy", "migration-plan", "rbac"],
        output_sections=STANDARD_OUTPUT_SECTIONS,
        review_checklist=[
            "Frame findings as fit gaps, not implementation promises.",
            "Call out ownership boundaries between workload and platform teams.",
            "Highlight controls likely required in a compliant Landing Zone: identity, networking, policy, logging, backup, and private connectivity.",
        ],
        expected_gaps=["Landing Zone reference architecture", "Enterprise standards", "Network and identity landing patterns", "Backup control standards"],
        prompt_template=(
            "Assess the likely Landing Zone fit of this workload. Identify the visible fit gaps across network, identity, governance, logging, backup, and shared services, "
            "and state what evidence or standards are still missing before migration design can be finalized. Cite chunk IDs."
        ),
    ),
]

INTENTS_BY_NAME: Dict[str, AnalysisIntent] = {intent.name: intent for intent in _INTENTS}
DEFAULT_INTENT_ORDER: List[str] = [intent.name for intent in _INTENTS]


def resolve_intents(selected: List[str]) -> List[AnalysisIntent]:
    if not selected or selected == ["*"]:
        return [INTENTS_BY_NAME[name] for name in DEFAULT_INTENT_ORDER]

    resolved: List[AnalysisIntent] = []
    for name in selected:
        if name == "*":
            return [INTENTS_BY_NAME[item] for item in DEFAULT_INTENT_ORDER]
        if name not in INTENTS_BY_NAME:
            raise ValueError(
                f"Unsupported local analysis intent: {name!r}. Valid: {sorted(INTENTS_BY_NAME)}"
            )
        resolved.append(INTENTS_BY_NAME[name])
    return resolved
