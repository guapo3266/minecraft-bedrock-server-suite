// Reglas del asistente de primera configuracion (sin React: probado con vitest).
//
// Pasos: 1 configuracion, 2 instalar BDS (solo si faltaba al abrir el
// asistente) y el final. Los indicadores de paso permitian saltar al final sin
// guardar la configuracion ni instalar BDS; "Finalizar" volvia atras con un
// mensaje que no se veia (2026-10-21). Solo se puede ir a un paso cuyas
// condiciones previas estan cumplidas.
export function ultimoPaso(bdsInstalled) {
  return bdsInstalled ? 2 : 3;
}

export function pasoMaximo({ saved, installed, bdsInstalled }) {
  if (!saved) return 1;
  if (!bdsInstalled && !installed) return 2;
  return ultimoPaso(bdsInstalled);
}
