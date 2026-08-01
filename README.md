# Voz — Dictado por voz local con Whisper

Voz es una herramienta de dictado por voz que ejecuta **Whisper** localmente mediante `faster-whisper`. Sin conexión a internet, sin enviar audio a ningún servidor.

## ⚡ Cómo funciona

1. **Abrís Voz** → primera vez: ventana de Configuración para elegir idioma y micrófono
2. **F10** para empezar a grabar (incluso si la ventana está minimizada)
3. **F10** otra vez para detener
4. Whisper transcribe automáticamente
5. El texto se copia al **portapapeles** y se guarda en `data/dictations/`
6. **F10** funciona incluso si la app está minimizada
7. Cerrar la ventana → cierra el programa completamente

## 📦 Requisitos

- **Windows 10/11** (no testeado en otras plataformas)
- **4 GB RAM mínimo** (8 GB recomendado)
- **Micrófono** (cualquier dispositivo de entrada de audio)
- ~**1.5 GB de espacio** para el modelo Whisper (descarga única)

## 🚀 Instalación

1. Descargar la carpeta `dist/voz/` completa (incluye `voz.exe` + `_internal/`)
2. Ejecutar `voz.exe` con doble clic (no requiere instalación)
3. Presionar **F10** para comenzar — el modelo se precarga al iniciar la app

### Para distribución

Solo necesitás compartir:

```
dist/voz/           ← ZIP → ~120-140 MB comprimido
├── voz.exe         ← 19 MB (lanzador)
└── _internal/      ← 320 MB (Python + dependencias)
```

El usuario descomprime, ejecuta `voz.exe`, y el modelo se descarga automáticamente al primer F10.

## 🎮 Atajos y uso

| Tecla/Acción | Descripción |
|---|---|
| **F10** | Iniciar/detener grabación (toggle, funciona en background) |
| **Botón Copiar** | Copia todo el texto al portapapeles |
| **Botón Limpiar** | Borra el texto acumulado |
| **Botón Guardar como...** | Guarda el texto en un archivo `.txt` |
| **Botón Configurar** | Ajustes: idioma, micrófono, tecla rápida |

## 🏗️ Arquitectura

```
voz/
├── main.py                  ← Entry point (GUI-only)
├── core/                    ← Capa pura (sin GUI)
│   ├── config.py            ← Configuración central (config.json)
│   ├── recorder.py          ← Captura de micrófono (sounddevice)
│   ├── transcriber.py       ← Transcripción (faster-whisper)
│   ├── clipboard.py         ← Portapapeles (pyperclip)
│   ├── storage.py           ← Persistencia (JSON + TXT)
│   └── models.py            ← Dataclasses (TranscriptionResult, Segment)
├── gui/                     ← Capa de interfaz (Tkinter)
│   ├── dictation_app.py     ← Ventana principal + state machine
│   ├── settings_window.py   ← Ventana de configuración
│   └── hotkey_listener.py   ← Tecla global F10 (pynput)
├── tests/                   ← Tests unitarios y de smoke (37 tests)
│   ├── test_models.py
│   ├── test_clipboard.py
│   ├── test_storage.py
│   ├── test_config.py
│   └── test_smoke.py
├── data/
│   ├── dictations/          ← Transcripciones guardadas (.json + .txt)
│   └── voz.log              ← Log de actividad
└── models/
    └── whisper/             ← Modelo Whisper cacheado
```

### Principios arquitectónicos

| Principio | Descripción |
|---|---|
| **Separación de capas** | `core/` = lógica pura (no sabe de GUI), `gui/` = interfaz (no sabe de micrófono) |
| **State machine** | Estados: `idle → recording → transcribing → copying → storing → done → idle` |
| **Thread safety** | Transcripción en hilo separado, comunicación con GUI via `event_generate` |
| **Precarga del modelo** | Whisper se carga en background al iniciar para que la primera transcripción sea instantánea |
| **Config centralizada** | Todos los valores mágicos en `core/config.py` |

## 🧠 Tecnologías

| Componente | Librería | Propósito |
|---|---|---|
| **Modelo ASR** | [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (v1.2.1) | Transcripción local con CTranslate2 |
| **Modelo** | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | Whisper turbo (español optimizado) |
| **Backend** | [`CTranslate2`](https://github.com/OpenNMT/CTranslate2) | Inferencia optimizada en CPU/GPU |
| **Audio input** | [`sounddevice`](https://python-sounddevice.readthedocs.io/) | Captura de micrófono (PortAudio) |
| **GUI** | [`Tkinter`](https://docs.python.org/3/library/tkinter.html) | Interfaz gráfica nativa de Windows |
| **Hotkey global** | [`pynput`](https://pynput.readthedocs.io/) | Tecla F10 global (incluso en background) |
| **Clipboard** | [`pyperclip`](https://pyperclip.readthedocs.io/) | Copia al portapapeles |
| **Logging** | `logging` estándar | Log a archivo + supresión de ruido |
| **Build** | [`PyInstaller`](https://pyinstaller.org/) (v6.20) | Empaquetado en `.exe` single-folder |

## 📐 Decisiones técnicas

### ¿Por qué `--onedir` y no `--onefile`?

El modelo Whisper pesa ~1.5 GB. PyInstaller no puede empaquetar eso dentro de un solo `.exe`
de forma práctica. El modelo se guarda en `models/whisper/` junto al ejecutable
para que toda la app viva en una sola carpeta autocontenida.

### ¿Por qué Turbo y no Small/Base?
Whisper **turbo** ofrece la mejor relación calidad/velocidad. En una Beelink Ryzen 7 7840HS, transcribe 60 segundos de audio en ~14 segundos (tras la carga inicial). Consume ~1.2 GB de RAM.

### ¿Por qué F10 y no un botón en pantalla?
F10 permite dicatar mientras se trabaja en otra aplicación. El hotkey listener usa `pynput` con `on_release` + debounce de 500ms para evitar disparos duplicados.

### ¿Por qué no hay system tray?
Se eliminó intencionalmente para simplificar. Cerrar ventana = cerrar programa. Sin iconos en segundo plano.

### ¿Cómo maneja el sample rate del micrófono?
Diferentes micrófonos usan diferentes frecuencias (48000 Hz, 44100 Hz, etc.). Voz detecta automáticamente el sample rate nativo del dispositivo y resamplea a 16000 Hz para Whisper usando `scipy.signal.resample`.

### ¿Por qué excluir `unittest` del build causaba errores?
Algunas dependencias (cómo `tokenizers` o `huggingface_hub`) importan `unittest` internamente para compatibilidad. Excluirlo del build rompía esas dependencias.

## ⚡ Rendimiento

Equipo de prueba: **Beelink Ryzen 7 7840HS, 32 GB RAM, Windows 11**

| Métrica | Valor |
|---|---|
| **RAM en uso** | ~1.2 GB (modelo turbo cargado) |
| **Primera carga del modelo** | ~3 minutos (descarga + compilación CTranslate2) |
| **Transcripción (segunda vez en adelante)** | 50 s de audio → ~14 s de proceso |
| **Modelo en disco** | ~1.5 GB (se duplica a ~3 GB en Windows sin symlinks) |
| **Temperatura CPU** | ~75-80°C durante transcripción intensiva |

> ⚠️ **Primer uso del modelo**
> 1. **Descarga**: Al primer inicio, Whisper descarga ~1.5 GB desde HuggingFace en background. Tiempo variable según internet.
> 2. **Carga en RAM**: Cada inicio, el modelo se precarga automáticamente mientras ves la ventana principal lista.
> 3. **Ya en uso**: Transcripciones casi instantáneas (~4 s para 5 s de audio en CPU moderna).

## 🐛 Solución de problemas

| Problema | Causa | Solución |
|---|---|---|
| "Invalid sample rate" | Micrófono no soporta 16000 Hz | Se resuelve automáticamente (resampleo) |
| "No module named 'unittest'" | Excluido del build | Se quitó de `excludes` en `build.spec` |
| Ventana negra sin contenido | Resolución muy baja | Redimensionar la ventana o ajustar `geometry` |
| El programa no arranca | Dependencias faltantes | Ejecutar `python main.py` desde PowerShell para ver el error |

## 🔧 Compilación

```powershell
# Instalar dependencias
pip install -r requirements.txt

# Compilar
pyinstaller build.spec
```

El `.exe` compilado está en `dist/voz/voz.exe`.

## 📄 Licencia

MIT