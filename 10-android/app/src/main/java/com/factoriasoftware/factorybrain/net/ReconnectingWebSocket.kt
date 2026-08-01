package com.factoriasoftware.factorybrain.net

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * Cliente WebSocket con reconexión automática (T-FB017-US01-01, criterio
 * de aceptación explícito: "cliente... con reconexión automática ante
 * corte de red" — base para el criterio 5 de la Story: "si la conexión se
 * interrumpe, la app reintenta sin perder el estado ya cargado en
 * pantalla").
 *
 * Backoff fijo simple (no exponencial): v1 de una app de un único
 * operador sobre una red Tailscale local — la ventana de reconexión
 * esperable es de segundos (el móvil recupera Tailscale), no minutos, así
 * que un backoff exponencial complicaría el código sin mejorar la
 * experiencia real. Mismo criterio de simplicidad ya aplicado en el
 * backend Python (ver `job_dispatch.py`: "polling simple... sin necesidad
 * real en v1").
 *
 * No pierde el estado ya cargado en pantalla al reconectar: esta clase
 * solo gestiona la conexión de transporte, nunca limpia el estado de UI
 * — quien la usa (un ViewModel) decide qué hacer con los mensajes
 * entrantes; el estado ya renderizado en pantalla no depende de que la
 * conexión siga viva.
 */
class ReconnectingWebSocket(
    private val url: String,
    private val scope: CoroutineScope,
    private val httpClient: OkHttpClient = BackendClient.defaultHttpClient(),
    private val reconnectDelayMillis: Long = 3_000L,
) {
    sealed interface ConnectionEvent {
        data object Connected : ConnectionEvent
        data class MessageReceived(val text: String) : ConnectionEvent
        data object Disconnected : ConnectionEvent
    }

    private val _events = MutableSharedFlow<ConnectionEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<ConnectionEvent> = _events

    private var webSocket: WebSocket? = null
    private var stoppedIntentionally = false

    fun start() {
        stoppedIntentionally = false
        connect()
    }

    fun stop() {
        stoppedIntentionally = true
        webSocket?.close(1000, "client stop")
        webSocket = null
    }

    private fun connect() {
        val request = Request.Builder().url(url).build()
        webSocket = httpClient.newWebSocket(request, listener)
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            _events.tryEmit(ConnectionEvent.Connected)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            _events.tryEmit(ConnectionEvent.MessageReceived(text))
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            _events.tryEmit(ConnectionEvent.Disconnected)
            scheduleReconnect()
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            _events.tryEmit(ConnectionEvent.Disconnected)
            scheduleReconnect()
        }
    }

    private fun scheduleReconnect() {
        if (stoppedIntentionally) return
        scope.launch {
            delay(reconnectDelayMillis)
            if (scope.isActive && !stoppedIntentionally) {
                connect()
            }
        }
    }
}
