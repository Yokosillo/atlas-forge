/* Factory Brain — cliente WebSocket con reconexión automática
 * (T-FB021-US04-01, criterio de aceptación explícito: "un corte de
 * conexión WebSocket reconecta automáticamente sin perder lo ya mostrado
 * en pantalla").
 *
 * Envoltura de transporte sobre el `WebSocket` nativo del navegador, con
 * el MISMO criterio ya documentado en `ReconnectingWebSocket.kt`
 * (Android):
 *
 *   - Backoff fijo simple (no exponencial): v1 de una app de un único
 *     operador sobre una red Tailscale local — la ventana de reconexión
 *     esperable es de segundos (la máquina recupera Tailscale), no
 *     minutos, así que un backoff exponencial complicaría el código sin
 *     mejorar la experiencia real. Mismo criterio de simplicidad ya
 *     aplicado en el backend Python (`job_dispatch.py`: "polling
 *     simple... sin necesidad real en v1").
 *
 *   - No pierde el estado ya cargado en pantalla al reconectar: esta
 *     clase solo gestiona la conexión de transporte, nunca limpia el
 *     estado de UI — quien la usa (la sección Jobs de `app.js`) decide
 *     qué hacer con los mensajes entrantes; el estado ya renderizado en
 *     pantalla no depende de que la conexión siga viva.
 *
 * API (misma forma que la clase Kotlin, adaptada a scripts clásicos):
 *
 *   var socket = new ReconnectingWebSocket(url, {
 *     reconnectDelayMillis: 3000,   // opcional, backoff fijo simple
 *     onopen:    function () {...}, // conexión establecida
 *     onmessage: function (event) {...}, // event.data = texto crudo
 *     onclose:   function (event) {...}, // conexión caída / reconexión pendiente
 *   });
 *   socket.start(); // conectar (reconecta tras cortes)
 *   socket.stop();  // cierre definitivo y controlado (sin reconexión)
 *
 * Carga: script clásico (NO módulo ES). Se expone el objeto global
 * `ReconnectingWebSocket`, cargado ANTES de `app.js` en `index.html`.
 */
(function () {
  "use strict";

  var DEFAULT_RECONNECT_DELAY_MILLIS = 3000;

  function ReconnectingWebSocket(url, options) {
    options = options || {};
    this.url = url;
    this.reconnectDelayMillis =
      typeof options.reconnectDelayMillis === "number"
        ? options.reconnectDelayMillis
        : DEFAULT_RECONNECT_DELAY_MILLIS;
    this.onopen = typeof options.onopen === "function" ? options.onopen : null;
    this.onmessage = typeof options.onmessage === "function" ? options.onmessage : null;
    this.onclose = typeof options.onclose === "function" ? options.onclose : null;
    this.onerror = typeof options.onerror === "function" ? options.onerror : null;

    this._ws = null; // WebSocket nativo actual (null cuando está caído)
    this._stoppedIntentionally = false;
    this._reconnectTimer = null;
  }

  /** Conecta (o reconecta). Tras `stop()` se reanuda con `start()`. */
  ReconnectingWebSocket.prototype.start = function () {
    this._stoppedIntentionally = false;
    this._connect();
  };

  /** Cierre definitivo y controlado: corta la reconexión pendiente y no
   *  vuelve a conectar. Quien lo usa (la sección Jobs al salir de la
   *  pestaña) conserva su estado propio intacto. */
  ReconnectingWebSocket.prototype.stop = function () {
    this._stoppedIntentionally = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      try {
        this._ws.close(1000, "client stop");
      } catch (_err) {
        // El socket puede estar ya en un estado en el que close() falla;
        // el cierre es definitivo de todos modos (no se reconectará).
      }
      this._ws = null;
    }
  };

  ReconnectingWebSocket.prototype._connect = function () {
    var self = this;
    if (this._stoppedIntentionally) return;

    var ws;
    try {
      ws = new WebSocket(this.url);
    } catch (_err) {
      // URL inválida o WebSocket no disponible: se reintenta con el
      // mismo backoff (no se pierde nada, igual que un corte de red).
      this._scheduleReconnect();
      return;
    }

    this._ws = ws;

    ws.onopen = function () {
      if (self._ws !== ws) return; // socket obsoleto (ya se detuvo/reconectó)
      if (self.onopen) self.onopen();
    };

    ws.onmessage = function (event) {
      if (self._ws !== ws) return;
      if (self.onmessage) self.onmessage(event);
    };

    ws.onclose = function (event) {
      if (self._ws !== ws) return;
      self._ws = null;
      if (self.onclose) self.onclose(event);
      self._scheduleReconnect();
    };

    // `onerror` siempre va seguido de `onclose` en el navegador: la
    // reconexión se programa SOLO en `onclose` para no programarla dos
    // veces por el mismo corte.
    ws.onerror = function (event) {
      if (self._ws !== ws) return;
      if (self.onerror) self.onerror(event);
    };
  };

  ReconnectingWebSocket.prototype._scheduleReconnect = function () {
    var self = this;
    if (this._stoppedIntentionally) return;
    if (this._reconnectTimer) return; // una reconexión pendiente a la vez
    this._reconnectTimer = setTimeout(function () {
      self._reconnectTimer = null;
      if (!self._stoppedIntentionally) self._connect();
    }, this.reconnectDelayMillis);
  };

  window.ReconnectingWebSocket = ReconnectingWebSocket;
})();
