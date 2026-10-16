# LiquidGlass — Minecraft Bedrock Server Suite

Módulo integrado en `gui_frontend/src/vendor/liquidglass.js` para las superficies
decorativas de la suite. Se importa como ES module local, sin globals ni CDN.
No captura contenido de consola, formularios o asistente IA.

## Adaptación mantenida por la suite

El módulo conserva límite de DPR 2, ciclo de vida cancelable e idempotente,
invalidación por cambios, pausa en segundo plano y limpieza ante fallos WebGL.
Las superficies estáticas permanecen inactivas hasta una invalidación explícita.
Se evita incrustar fuentes o capturar contenido de los hosts vacíos. Los eventos
son propios de la suite y el clonador de textarea usa `textContent`.

Estos parches incluyen trabajo heredado de las versiones de referencia; esta
descripción identifica su uso actual, no atribuye su autoría exclusiva a la suite.

## Procedencia histórica

- Proyecto original: https://github.com/ybouane/liquidglass.
- Copia de referencia local anterior: SHA-256 `9cbe94189fae695b2524b5dc7f750ba7ea8c37c71d3a6f86f34158fe193cc0c4`.
- Integración intermedia: Nokia WiFi Manager, `frontend/src/vendor/liquidglass.js`,
  SHA-256 `fe183c67ed33f94640921318bdeb7118968e22a68c8bff6ccdd2bfbb0ef273d9`.
- Integración inicial en esta suite (2026-10-12): SHA-256 `15315d32259b9f8d64fa5d654618042334ef2cf74d0b281c9fc219d864afede2`.
- Módulo vigente: SHA-256 `a267575ca1c74a75068ba660330354b78dab0c30e6744f2dd3d4f3bcf685eb33`.

La referencia de origen declara MIT. Incluye html-to-image (MIT,
Copyright 2021 BUBBLE). Conservar esta procedencia y los avisos de licencia al
actualizar el motor.

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
