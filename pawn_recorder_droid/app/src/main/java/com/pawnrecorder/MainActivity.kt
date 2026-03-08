package com.pawnrecorder

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.chaquo.python.Python
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private val TAG = "PawnRecorder"
    private val PORT = 8765

    private lateinit var webView: WebView

    private val recordAudioPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                Log.d(TAG, "RECORD_AUDIO granted.")
                startPythonServer()
            } else {
                Log.w(TAG, "RECORD_AUDIO denied — microphone unavailable.")
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // ── 1. Request RECORD_AUDIO permission ────────────────────────────────
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            recordAudioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            startPythonServer()
        }

        // ── 2. Configure WebView ──────────────────────────────────────────────
        webView = WebView(this)
        setContentView(webView)

        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            cacheMode = WebSettings.LOAD_NO_CACHE
            allowContentAccess = true
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                Log.d(TAG, "WebView loaded: $url")
            }
        }

        // Load a local splash that polls localhost until Flask is ready,
        // then navigates to the real UI. No fixed delay needed.
        val splash = """
            <!DOCTYPE html><html>
            <head><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
            <body style="margin:0;background:#0d0d0d;color:#e8e8e8;
                         display:flex;align-items:center;justify-content:center;
                         height:100vh;font-family:sans-serif;flex-direction:column;gap:16px">
              <div style="font-size:2rem">&#127897;</div>
              <div id="msg" style="font-size:1rem;color:#888">Starting server…</div>
              <script>
                var attempts = 0;
                function tryLoad() {
                  fetch('http://127.0.0.1:$PORT/api/status')
                    .then(function(r) {
                      if (r.ok) { window.location = 'http://127.0.0.1:$PORT/'; }
                      else { retry(); }
                    })
                    .catch(function() { retry(); });
                }
                function retry() {
                  attempts++;
                  document.getElementById('msg').textContent =
                    'Starting server… (' + attempts + ')';
                  setTimeout(tryLoad, 800);
                }
                setTimeout(tryLoad, 500);
              </script>
            </body></html>
        """.trimIndent()

        webView.loadDataWithBaseURL(
            "http://127.0.0.1:$PORT/",   // base URL = same origin → fetch() works
            splash,
            "text/html",
            "utf-8",
            null
        )
    }

    private fun startPythonServer() {
        Log.d(TAG, "Starting Python server…")
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val py = Python.getInstance()
                val startup = py.getModule("startup")
                startup.callAttr("start_server")
                Log.d(TAG, "start_server() returned.")
            } catch (e: Exception) {
                Log.e(TAG, "Python startup error: ${e.message}", e)
            }
        }
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack()
        else super.onBackPressed()
    }
}
