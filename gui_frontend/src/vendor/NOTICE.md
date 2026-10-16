# LiquidGlass local bundle

Source: Nokia WiFi Manager, `frontend/src/vendor/liquidglass.js`, snapshot
adapted to Minecraft Bedrock Server Suite on 2026-10-12. The Nokia snapshot
itself originated in the local Minecraft liquid-glass reference demo.
Upstream: https://github.com/ybouane/liquidglass
Original SHA-256: 9cbe94189fae695b2524b5dc7f750ba7ea8c37c71d3a6f86f34158fe193cc0c4
Nokia snapshot SHA-256: fe183c67ed33f94640921318bdeb7118968e22a68c8bff6ccdd2bfbb0ef273d9
Suite snapshot SHA-256: 15315d32259b9f8d64fa5d654618042334ef2cf74d0b281c9fc219d864afede2

The upstream package manifest declares MIT. This snapshot already contains
local decoding, scheduling and per-element dirty-tracking patches from the
reference demo. It includes html-to-image (MIT, Copyright 2021 BUBBLE).
Retain this provenance and all existing source comments when updating.

NWM changes: ES-module export (no window globals), DPR cap 2, cancellable and
idempotent lifecycle, event-driven idle rendering, pause/resume, cleanup when WebGL is unavailable, skip
font embedding and content captures for empty decorative hosts, and a frame
notification for background-only contrast sampling. Only this
adapted module is imported; no CDN or network fallback is used.

Suite adaptation: frame event names are local to this app; textarea cloning
uses `textContent` rather than interpreting its value as HTML. Hosts remain
empty decorative surfaces: no server logs, forms or AI content are captured.

## MIT license notice

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
