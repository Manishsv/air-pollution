# AirOS developer templates (starters only)

Copy these files when sketching a new vertical slice—**rename placeholders** (`<domain_name>`, `<provider_name>`, `<consumer_name>`) and align filenames with repo conventions before registering in `specifications/manifest.json`.

Templates are documentation/starter scaffolding only—they are **not** imported by AirOS runtime.

| Template | Typical destination after hand-copy |
|---------|--------------------------------------|
| `provider_contract.template.schema.json` → `*.schema.json` | `specifications/provider_contracts/` |
| `consumer_contract.template.schema.json` → `*.schema.json` | `specifications/consumer_contracts/` |
| `provider_example.template.json` | `specifications/examples/<domain>/` |
| `consumer_example.template.json` | `specifications/examples/<domain>/` |
| `application_builder.template.py` | `urban_platform/applications/<domain>/` |
| `dashboard_panel.template.py` | `review_dashboard/components/` |
| `deployment_readme.template.md` | `deployments/examples/<your_demo>/README.md` |

See [`docs/BEGINNER_DEVELOPER_GUIDE.md`](../BEGINNER_DEVELOPER_GUIDE.md) for the beginner walk-through.
