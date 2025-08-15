# Macro selection rules (auto-generated from MDB CSVs)

Files:
- function_to_xml_macro_map.yaml — Function → list of XML Macro Name(s), ordered by detFunctionMacroKind.Order
- macro_selection_rules.yaml — per function, the ordered macro candidates with MacroSelectionCriteria
- macro_selector_context.example.yaml — example values for variables referenced in criteria: BRDVIVAVER, HWSET

Rule syntax (from detFunctionMacroKind.MacroSelectionCriteria):
- `?VAR <op> VALUE` where `<op>` ∈ {==, !=, >=, <=, >, <}
- VAR names seen: BRDVIVAVER, HWSET
- Values may be integers/floats or dotted versions (e.g., 11.0.0.0). Compare as numbers or versions accordingly.

Selection algorithm:
1. If tabFunction.IgnoreMacroSelectionCriteria == 1 → pick the first candidate by Order.
2. Else evaluate candidates by Order and pick the first whose criteria evaluates True against the context (macro_selector_context.yaml).
3. If none match, fall back to the first by Order.

This mirrors the MDB logic encoded in detFunctionMacroKind and tabFunction.
