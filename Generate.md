https://www.drawio.com/assets/mxfile.xsd
https://www.drawio.com/doc/faq/ai-drawio-generation
https://www.drawio.com/doc/faq/format-custom-shape-library#:~:text=Uncompressed%20XML%20properties%20must%20be,by%20a%20backslash%20like%20%5C%22%20.&text=By%20default%2C%20when%20exporting%20a,in%20the%20draw.io%20configuration.&text=To%20compress%20the%20XML%20property,the%20draw.io%20conversion%20tool.

Generate and validate draw.io diagrams with AI
draw.io diagram files (.drawio) use a well-defined XML format that AI systems can generate and validate programmatically. Two reference documents are provided to help AI models produce correct diagram files.

Reference documents
draw.io Style Reference — A comprehensive guide covering the complete .drawio file structure, all style properties, shape types, edge routing, color palettes, HTML labels, layers, groups, and complete examples. This is the primary document an AI system needs to generate valid draw.io files.

mxfile.xsd — An XML Schema Definition (XSD) for validating the structure of .drawio files. Use this to validate AI-generated output before saving or delivering it to users.

draw.io MCP server
The draw.io MCP server provides four ways to integrate AI-generated diagrams with draw.io:

Approach	What it does	Production endpoint
MCP App Server	Renders diagrams inline in AI chat as an interactive viewer	mcp.draw.io/mcp — add as a remote MCP server
MCP Tool Server	Opens diagrams in the draw.io editor in your browser (supports XML, CSV, and Mermaid)	@drawio/mcp on npm — run with npx @drawio/mcp
Skill + CLI	Generates native .drawio files with optional PNG/SVG/PDF export via the draw.io Desktop CLI	Copy skill file to Claude Code skills directory
Project Instructions	Claude generates draw.io URLs via Python — no installation required	Paste instructions into a Claude Project
File format overview
A full .drawio file is XML with this structure:

<mxfile>
  <diagram id="page-1" name="Page-1">
    <mxGraphModel dx="0" dy="0" grid="1" gridSize="10" guides="1"
                  tooltips="1" connect="1" arrows="1" fold="1"
                  page="1" pageScale="1" pageWidth="850" pageHeight="1100"
                  math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- Diagram elements go here with parent="1" -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
Each diagram element is an mxCell with either vertex="1" (shapes) or edge="1" (connectors). Visual appearance is controlled via a style attribute containing semicolon-separated key=value pairs.

Simplified format: mxGraphModel only
AI systems can also generate just the <mxGraphModel> element without the <mxfile> and <diagram> wrappers. This is a valid draw.io XML fragment and is easier for AI to generate since there are fewer nesting levels and no need for diagram/page metadata:

<mxGraphModel>
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="2" value="Hello" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
      <mxGeometry x="100" y="100" width="120" height="60" as="geometry" />
    </mxCell>
  </root>
</mxGraphModel>
draw.io accepts both formats. When a bare <mxGraphModel> is opened, draw.io wraps it in the <mxfile> and <diagram> elements automatically. The simplified format is recommended for AI generation when multi-page support is not needed.

File-level variables
The <mxfile> element supports a vars attribute containing a JSON object of key-value pairs. These are global variables that can be referenced in labels and tooltips using %variableName% placeholder syntax. Users can edit them via File > Properties > Edit Data in the draw.io editor.

To enable placeholder substitution on a cell, you must set placeholders="1" on the UserObject (or as a style property on a plain mxCell). Without this flag, %name% tokens are rendered as literal text.

<mxfile vars='{"project":"Atlas","version":"2.1","author":"Jane Doe"}'>
  <diagram id="page-1" name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <UserObject id="2" label="Project: %project% v%version%" placeholders="1">
          <mxCell style="text;html=1;align=center;" vertex="1" parent="1">
            <mxGeometry x="100" y="100" width="200" height="40" as="geometry" />
          </mxCell>
        </UserObject>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
When the diagram is rendered, %project% is replaced with Atlas and %version% with 2.1. File-level variables are only available when using the full <mxfile> format (not the simplified <mxGraphModel>-only format).

Compressed format
The .drawio file format also supports a compressed representation where the diagram content inside the <diagram> element is deflate-compressed and Base64-encoded instead of containing an <mxGraphModel> child element directly. While draw.io uses this compressed format by default when saving files, AI systems should not generate compressed content. Compressed XML uses more tokens (the Base64 encoding is larger than the raw XML), is not human-readable, and cannot be validated or debugged without decompression.

If you need to create compressed content anyway (e.g. for passing diagram data via URLs), the process is:

Take the XML string (either the full <mxfile> or just the <mxGraphModel>)
URL-encode it with encodeURIComponent()
Compress with raw DEFLATE (not zlib — no headers)
Base64-encode the compressed bytes
In JavaScript with the pako library:

function compressDrawioXml(xml) {
  var encoded = encodeURIComponent(xml);
  var compressed = pako.deflateRaw(encoded);
  return btoa(Array.from(compressed, function(b) {
    return String.fromCharCode(b);
  }).join(""));
}
Key rules for AI generation
Always include the two structural cells — <mxCell id="0"/> (root container) and <mxCell id="1" parent="0"/> (default layer) are mandatory.
Use uncompressed XML — AI should generate plain XML, not compressed/Base64-encoded content.
All IDs must be unique within a diagram.
Vertices need vertex="1", edges need edge="1"** — these are mutually exclusive.
Style strings use key=value; format — e.g. "rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;".
Match perimeters to shapes — non-rectangular shapes need a matching perimeter= value (e.g. ellipse needs perimeter=ellipsePerimeter).
Coordinates: (0,0) is top-left — x increases rightward, y increases downward.
HTML in value must be XML-escaped — use &lt;, &gt;, &amp;, &quot;.
Children of groups use relative coordinates — positions are relative to the parent container, not the canvas.
Minimal shape example
<mxCell id="2" value="Hello" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="120" height="60" as="geometry" />
</mxCell>
Minimal edge example
<mxCell id="e1" value="" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
Custom metadata with object / UserObject
To attach custom key-value metadata to a shape (visible in Edit > Edit Data in draw.io), wrap the mxCell in an object or UserObject element. Both names are interchangeable — object is shorter and is what draw.io writes when saving files:

<object id="srv1" label="Web Server" ip="10.0.1.10" environment="production">
  <mxCell style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
    <mxGeometry x="100" y="100" width="140" height="70" as="geometry" />
  </mxCell>
</object>
These wrappers are not limited to diagram shapes — they can also be used on the root container cell (id="0") and on layer cells (parent="0") to attach custom metadata at the diagram or layer level. This metadata is editable via Edit > Edit Data in the draw.io editor when the root or a layer is selected.

<root>
  <!-- Root container with custom metadata -->
  <object id="0" label="" diagramType="network" lastReviewed="2025-03-01">
    <mxCell />
  </object>
  <!-- Layer with custom metadata -->
  <object id="1" label="Infrastructure" owner="ops-team" locked="false">
    <mxCell parent="0" />
  </object>
  <!-- Diagram elements -->
  <mxCell id="2" value="Server" style="rounded=1;html=1;" vertex="1" parent="1">
    <mxGeometry x="100" y="100" width="120" height="60" as="geometry" />
  </mxCell>
</root>
Placeholder scoping and resolution
When placeholders="1" is set on an object (or UserObject), %name% tokens in its label and tooltip are resolved by walking up the containment hierarchy. Variables are looked up in this order, and the first match wins:

Cell — attributes on the object itself
Parent container — attributes on the parent group or swimlane
Layer — attributes on the layer cell (parent="0")
Root — attributes on the root container cell (id="0")
File — the vars JSON attribute on the <mxfile> element
This means a shape can override a file-level variable by defining an attribute with the same name on its own object, and a layer can provide defaults for all shapes it contains.

<mxfile vars='{"env":"staging"}'>
  <diagram id="page-1" name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0" />
        <object id="1" label="Production" env="production">
          <mxCell parent="0" />
        </object>
        <!-- This shape resolves %env% to "production" from the layer, -->
        <!-- overriding the file-level "staging" value -->
        <object id="2" label="Environment: %env%" placeholders="1">
          <mxCell style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
            <mxGeometry x="100" y="100" width="160" height="60" as="geometry" />
          </mxCell>
        </object>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
Opening AI-generated diagrams in draw.io
Opening in the editor with the #create URL
To open an AI-generated diagram directly in the draw.io editor, compress the XML and pass it via the URL hash using the #create parameter:

https://app.diagrams.net/?grid=0&pv=0#create=ENCODED_JSON
The #create value is a URL-encoded JSON object:

{
  "type": "xml",
  "compressed": true,
  "data": "BASE64_DEFLATED_XML"
}
The type field can be "xml", "csv", or "mermaid". The data field contains the diagram content compressed as described in the compressed format section above.

Complete JavaScript example for generating an editor URL from XML:

function generateDrawioEditUrl(xml) {
  var encoded = encodeURIComponent(xml);
  var compressed = pako.deflateRaw(encoded);
  var base64 = btoa(Array.from(compressed, function(b) {
    return String.fromCharCode(b);
  }).join(""));
  var createObj = { type: "xml", compressed: true, data: base64 };

  return "https://app.diagrams.net/?pv=0&grid=0#create="
    + encodeURIComponent(JSON.stringify(createObj));
}
Optional query parameters:

lightbox=1 — open in read-only lightbox view
edit=_blank — add an edit button that opens the editor in a new tab
dark=1 — enable dark mode
grid=0 — hide the grid
pv=0 — hide the page view selector
border=10 — set the border size in pixels
Embedding with the viewer
To display a diagram inline in a web page without the full editor, use the draw.io viewer library. Load viewer-static.min.js from the CDN, then create a <div> with the diagram configuration in a data-mxgraph attribute:

<script src="https://viewer.diagrams.net/js/viewer-static.min.js" async></script>

<div class="mxgraph" data-mxgraph='{"highlight":"#0000ff","nav":true,"resize":true,"toolbar":"zoom layers tags","xml":"DIAGRAM_XML_HERE"}'></div>
The viewer automatically processes all elements with class="mxgraph" when the library loads. The xml property in the JSON configuration contains the raw (uncompressed) diagram XML. The container element must have a non-zero width for the viewer to render correctly.

Configuration options for the data-mxgraph JSON:

xml — the diagram XML (uncompressed)
highlight — highlight color for hover effects
nav — enable navigation controls
resize — allow the viewer to resize
toolbar — space-separated list of toolbar buttons (e.g. "zoom layers tags")
dark-mode — set to "auto" to follow the page’s color scheme
After the viewer has loaded, call GraphViewer.processElements() to render any dynamically added diagram elements.

Validation
Use the mxfile.xsd schema to validate the XML structure of generated files. The schema covers the element hierarchy and attribute types. For style string validation (which properties and values are valid), refer to the Style Reference.

The style reference also includes a validation checklist covering the most common issues in AI-generated diagrams.

---

## Azure-to-drawio: Deterministic "Beta-Dumb-AI" Notes

Goal: Reproduce useful architecture diagrams from extracted data with deterministic transforms (no model inference at runtime).

### Deterministic Actions

1. Canonicalize inputs:
  - Normalize resource IDs, type casing, and connection direction.
  - Deduplicate edges by `(source, target, kind)`.
2. Apply scenario templates:
  - `vm-network-immediate`
  - `vm-application-interactions`
  - `full-balanced`
3. Enforce allowed edge intents by diagram type:
  - `network` => `network-flow`
  - `application` => `integration`, `data-flow`
  - `balanced` => all intents
4. Enforce network scope rules:
  - `immediate-vm-network` => keep only `vm->nic`, `nic->subnet`, `subnet->vnet`
5. Emit deterministic artifacts:
  - `scenario_spec.json`
  - `scenario_rules_applied.json`
  - `diagram.drawio` (+ optional `diagram.svg`, `diagram.png`)

### UI Preview Status (Implemented)

Artifact preview in the UI now supports:

- `.json` sampled preview
- `.drawio`, `.xml`, `.mxlibrary` XML snippet preview
- `.png`, `.svg` inline visual preview

Relevant files:

- `tools/azdisc_ui/__main__.py` (preview API)
- `tools/azdisc_ui/static/app.js` (preview rendering)
- `tools/azdisc_ui/templates/index.html` (preview panel)
- `tools/azdisc_ui/static/style.css` (image preview styling)

### Next Deterministic Milestones

1. [Done] Add `ScenarioSpec` schema and parser for controlled scenario text.
2. [Done] Add `ScenarioSpec -> graph` adapter.
3. Add template selector in UI to run deterministic scenario transforms.
4. Add regression fixtures with fixed expected node/edge outputs.

### ScenarioSpec Implementation (Current)

Added deterministic parsing and adapter scaffolding:

- `tools/azdisc/scenario_spec.py`
  - `ScenarioSpec`, `ScenarioResource`, `ScenarioConnection` dataclasses.
  - `parse_scenario_spec(text)` for section-based prompt parsing.
  - `scenario_spec_to_graph(spec)` for deterministic graph payload generation.
- `tools/azdisc/tests/test_scenario_spec.py`
  - parser section extraction coverage.
  - graph adapter coverage including synthesized actor nodes.