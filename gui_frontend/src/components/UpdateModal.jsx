import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import DecryptedText from './reactbits/DecryptedText';
import ShinyText from './reactbits/ShinyText';
import Magnet from './reactbits/Magnet';
import { DownloadMotionIcon, ShieldMotionIcon } from './hover/HardwareMotionIcons';
import { X, CheckCircle, AlertTriangle } from 'lucide-react';

export default function UpdateModal({ isOpen, onClose, updateInfo, onConfirmUpdate, isUpdating }) {
  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop Blur Overlay */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 bg-black/75 backdrop-blur-md"
        />

        {/* Hover.dev Spring Modal Card */}
        <motion.div
          initial={{ scale: 0.8, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.8, opacity: 0, y: 20 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
          className="relative z-10 w-full max-w-lg rounded-2xl border border-emerald-500/40 bg-slate-950 p-6 shadow-2xl overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/20 border border-emerald-500/40">
                <DownloadMotionIcon className="h-5 w-5 text-emerald-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">Actualizador Oficial Mojang BDS</h2>
                <p className="text-xs text-slate-400">Verificación de versión del ejecutable</p>
              </div>
            </div>
            <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body Content */}
          <div className="my-6 space-y-4">
            {updateInfo?.has_update ? (
              <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
                <div className="flex items-center gap-2 text-sm font-bold text-emerald-400">
                  <CheckCircle className="h-4 w-4" />
                  <span>¡NUEVA VERSIÓN DETECTADA DE MOJANG!</span>
                </div>
                <div className="mt-2 text-2xl font-extrabold text-white tracking-wider">
                  <DecryptedText text={`v${updateInfo.latest_version}`} />
                </div>
                <p className="mt-1 text-xs text-slate-300">
                  Versión actual en tu servidor: <span className="font-mono text-slate-400">{updateInfo.current_version}</span>
                </p>
              </div>
            ) : (
              <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-4">
                <div className="flex items-center gap-2 text-sm font-bold text-cyan-400">
                  <CheckCircle className="h-4 w-4" />
                  <span>TU SERVIDOR ESTÁ EN LA ÚLTIMA VERSIÓN</span>
                </div>
                <div className="mt-2 text-xl font-extrabold text-white">
                  Versión Activa: v{updateInfo?.current_version || "1.21.XX"}
                </div>
              </div>
            )}

            <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-2 text-xs text-slate-300">
              <div className="flex items-center gap-2 font-bold text-amber-400">
                <ShieldMotionIcon className="h-4 w-4 text-amber-400" />
                <span>Protocolo de Protección de Datos Activo:</span>
              </div>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>Se ejecutará un <strong className="text-white">Backup Preventivo Automático</strong> antes de actualizar.</li>
                <li>Tus mundos (<code className="text-emerald-400">worlds/</code>) y configs (<code className="text-emerald-400">server.properties</code>) no se borrarán.</li>
              </ul>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
            <button
              onClick={onClose}
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 hover:bg-white/10"
            >
              Cancelar
            </button>

            {updateInfo?.has_update && (
              <Magnet>
                <button
                  onClick={onConfirmUpdate}
                  disabled={isUpdating}
                  className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-5 py-2 text-xs font-bold text-black shadow-[0_0_20px_rgba(16,185,129,0.4)] hover:brightness-110 disabled:opacity-50"
                >
                  <DownloadMotionIcon className="h-4 w-4 text-black" />
                  <ShinyText text={isUpdating ? "Actualizando BDS..." : "Descargar & Actualizar Ahora"} />
                </button>
              </Magnet>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
