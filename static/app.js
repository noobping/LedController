const { createApp, ref, onMounted, nextTick, onUnmounted } = Vue;

createApp({
    setup() {
        const currentCommand = ref("");
        const messages = ref([
            { text: "Welcome to the LED Controller WebSocket Client!", type: 'info' }
        ]);
        let socket = null;

        // Example commands for autocomplete
        const knownCommands = [
            "christmas",
            "videolist",
            "video windows_21_dec",
            "stop",
            "brightness 255",
            "piano 0,0",
            "setall ffffff",
            "update 000000, ffffff, 000000, ffffff",
            "difference (0), ffffff, (1), 000000",
        ];

        const filteredSuggestions = ref([]);
        const selectedSuggestionIndex = ref(-1);
        const MAX_MESSAGES = 100;

        // Health check interval ID
        let healthCheckInterval = null;

        // Dynamically construct WebSocket and health URLs based on current location
        const host = window.location.hostname;
        const isSecure = window.location.protocol === 'https:';
        const wsProtocol = isSecure ? 'wss' : 'ws';
        const httpProtocol = isSecure ? 'https' : 'http';
        const wsPort = 8901; // Adjust if your WebSocket server uses a different port
        const wsUrl = `${wsProtocol}://${host}:${wsPort}/ws`;
        const healthUrl = `${httpProtocol}://${host}:${wsPort}/health`;

        // Connect to the WebSocket
        function connect() {
            socket = new WebSocket(wsUrl);

            socket.onopen = () => {
                messages.value.push({ text: "Connected to WebSocket.", type: 'info' });
                scrollToBottom();
            };

            socket.onmessage = (event) => {
                let incoming;
                let messageType = "info";

                try {
                    incoming = JSON.parse(event.data);
                    // Check for error or debug properties in the JSON payload.
                    if (incoming.error !== undefined) {
                        messageType = "error";
                    } else if (incoming.status !== undefined) {
                        messageType = "status";
                    } else if (incoming.includes("DEBUG")) {
                        messageType = "debug";
                    }
                    messages.value.push({
                        text: incoming.error !== undefined ? incoming.error :
                            (incoming.status !== undefined ? incoming.status : JSON.stringify(incoming)),
                        type: messageType
                    });
                } catch (e) {
                    // If the message isn't valid JSON, inspect the raw string.
                    const dataLower = event.data.toLowerCase();
                    if (dataLower.includes("debug")) {
                        messageType = "debug";
                    } else if (dataLower.includes("error")) {
                        messageType = "error";
                    }
                    messages.value.push({ text: event.data, type: messageType });
                }

                if (messages.value.length > MAX_MESSAGES) {
                    messages.value.shift();
                }
                scrollToBottom();
            };

            socket.onerror = (error) => {
                messages.value.push({ text: "WebSocket Error: " + (error.message || "Unknown error"), type: 'error' });
                scrollToBottom();
            };

            socket.onclose = () => {
                messages.value.push({ text: "WebSocket connection closed.", type: 'warning' });
                scrollToBottom();
                // Attempt to reconnect after 5 seconds
                setTimeout(connect, 5000);
            };
        }

        // New sendCommand function: it sends a JSON payload over the socket.
        function sendCommand() {
            const cmdText = currentCommand.value.trim();
            if (!cmdText) return;
            let jsonPayload;
            try {
                // If the input is valid JSON, use it directly.
                jsonPayload = JSON.parse(cmdText);
            } catch (e) {
                // Otherwise, treat it as a "command data" string.
                const parts = cmdText.split(" ");
                const command = parts[0];
                const data = parts.slice(1).join(" ") || null;
                jsonPayload = { command, data };
            }
            const jsonMessage = JSON.stringify(jsonPayload);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(jsonMessage);
                messages.value.push({ text: "> " + jsonMessage, type: 'command' });
                if (messages.value.length > MAX_MESSAGES) {
                    messages.value.shift();
                }
                currentCommand.value = "";
                filteredSuggestions.value = [];
                selectedSuggestionIndex.value = -1;
                scrollToBottom();
            } else {
                messages.value.push({ text: "WebSocket not connected.", type: 'error' });
                scrollToBottom();
            }
        }

        function filterSuggestions() {
            const input = currentCommand.value.toLowerCase();
            if (!input) {
                filteredSuggestions.value = [];
                selectedSuggestionIndex.value = -1;
                return;
            }
            filteredSuggestions.value = knownCommands.filter(cmd =>
                cmd.toLowerCase().startsWith(input)
            );
            selectedSuggestionIndex.value = -1;
        }

        function selectNextSuggestion() {
            if (filteredSuggestions.value.length > 0) {
                selectedSuggestionIndex.value =
                    (selectedSuggestionIndex.value + 1) % filteredSuggestions.value.length;
                currentCommand.value = filteredSuggestions.value[selectedSuggestionIndex.value];
            }
        }

        function selectPrevSuggestion() {
            if (filteredSuggestions.value.length > 0) {
                selectedSuggestionIndex.value--;
                if (selectedSuggestionIndex.value < 0) {
                    selectedSuggestionIndex.value = filteredSuggestions.value.length - 1;
                }
                currentCommand.value = filteredSuggestions.value[selectedSuggestionIndex.value];
            }
        }

        function chooseSuggestion(index) {
            currentCommand.value = filteredSuggestions.value[index];
            filteredSuggestions.value = [];
            selectedSuggestionIndex.value = -1;
        }

        function scrollToBottom() {
            nextTick(() => {
                const messagesContainer = document.querySelector(".messages");
                if (messagesContainer) {
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            });
        }

        async function checkHealth() {
            try {
                const response = await fetch(healthUrl);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                const unreachable = Object.entries(data).filter(([ip, status]) => status !== "OK");
                if (unreachable.length > 0) {
                    const ips = unreachable.map(([ip]) => ip).join(", ");
                    messages.value.push({
                        text: `Warning: The following devices are unreachable: ${ips}`,
                        type: 'warning'
                    });
                    console.warn("Unreachable devices:", unreachable);
                } else {
                    messages.value.push({ text: "All devices are healthy.", type: 'info' });
                }
            } catch (error) {
                messages.value.push({
                    text: `Error fetching health status: ${error.message}`,
                    type: 'error'
                });
                console.error("Health check failed:", error);
            } finally {
                scrollToBottom();
            }
        }

        onMounted(() => {
            messages.value.push({
                text: "Type a command and press Enter to send it as JSON to the server.",
                type: 'info'
            });
            messages.value.push({
                text: "Use the up and down arrow keys to select a suggestion and press Enter to choose it.",
                type: 'info'
            });
            messages.value.push({
                text: "Known commands: " + knownCommands.join(", "),
                type: 'info'
            });
            messages.value.push({
                text: "Connecting to WebSocket...",
                type: 'info'
            });
            connect();
            checkHealth();
            // Set up a periodic health check every 60 seconds
            healthCheckInterval = setInterval(checkHealth, 60000);
        });

        // Clean up on unmount
        onUnmounted(() => {
            if (socket) {
                socket.close();
            }
            if (healthCheckInterval) {
                clearInterval(healthCheckInterval);
            }
        });

        return {
            currentCommand,
            messages,
            filteredSuggestions,
            selectedSuggestionIndex,
            sendCommand,
            filterSuggestions,
            selectNextSuggestion,
            selectPrevSuggestion,
            chooseSuggestion,
        };
    },
}).mount("#app");