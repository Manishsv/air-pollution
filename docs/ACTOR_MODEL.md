# AirOS Actor Model

AirOS dashboards and decision packets must be designed around actors and decisions.

AirOS is **specs-first**: dashboards are **consumer contracts**, and the payloads they consume must conform to specifications under `specifications/consumer_contracts/`. Actor semantics and decision packets must be backed by **domain specifications** under `specifications/domain_specs/`.

## Actor: City Commissioner / Administrator

Needs:
- City-wide situational awareness
- Cross-department escalation
- Risk prioritization
- Resource allocation
- Public communication

Dashboard style:
- Executive summary
- City-level risk map
- Department-wise pending actions
- Critical alerts
- Trend and performance indicators

Decision packet expectations:
- Evidence summary with provenance and reliability
- Clear “what we know / what we don’t” caveats
- Explicit confidence / uncertainty and recommended verification steps
- Cross-department handoffs (who must act next)

## Actor: Ward Officer

Needs:
- Ward-level operational queue
- Field verification tasks
- Local issue prioritization
- Citizen complaint overlays
- Evidence for escalation

Dashboard style:
- Ward map
- Action queue
- Field task status
- Evidence packets
- Before/after outcomes

Decision packet expectations:
- Location-specific evidence bundle
- Checklist-style verification questions
- Safe next actions vs “do not act” conditions

## Actor: Department Engineer

Needs:
- Asset condition
- Network failures
- Inspection prioritization
- Maintenance planning
- Technical evidence

Dashboard style:
- Asset map
- Sensor status
- Reliability alerts
- Work-order candidates
- Technical diagnostics

Decision packet expectations:
- Technical diagnostics and anomaly context
- Asset identifiers and history
- Reliability flags and sensor health
- Recommended inspection scope

## Actor: Field Inspector

Needs:
- Clear task
- Location
- Evidence
- Verification checklist
- Ability to submit outcome

Dashboard style:
- Mobile-first task list
- Map navigation
- Photo/evidence capture
- Checklist
- Submit finding

Decision packet expectations:
- Minimal, unambiguous task definition
- Safety notes and constraints
- Evidence attachments and how to validate them
- Required outcome fields (structured)

## Actor: Citizen / Civil Society

Needs:
- Public information
- Service status
- Risk alerts
- Ability to report issues
- Trust and transparency

Dashboard style:
- Public map
- Simple alerts
- Report issue
- Status of action taken
- Non-sensitive open data

Decision-support constraints:
- Never present synthetic or low-confidence data as operational truth
- Prefer “awareness” and “verify” framing unless confidence gates pass