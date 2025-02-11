const { createApp, ref, onMounted, onUpdated, nextTick, onUnmounted } = Vue;

createApp({
    setup() {
        const currentCommand = ref("");
        const messages = ref([
            { text: "Welcome to the LED Controller WebSocket Client!", type: "info" },
        ]);
        let socket = null;

        // List of commands (for autocomplete/help)
        const knownCommands = [
            "log [level]",
            "videolist",
            "video <video_name>",
            "stop",
            "brightness <0-255>",
            "piano <controller,window> [persistent] [r, g, b]",
            "christmas",
            "setall <6-digit hex>",
            "update <400 comma-separated hex colors>",
            "difference <(index), hex, (index), hex, ...>",
        ];

        const videoList = ref([]);
        const filteredSuggestions = ref([]);
        const selectedSuggestionIndex = ref(-1);
        const MAX_MESSAGES = 100;

        // Health check interval ID
        let healthCheckInterval = null;

        // Dynamically construct WebSocket and HTTP URLs based on the current location
        const host = window.location.hostname;
        const isSecure = window.location.protocol === "https:";
        const wsProtocol = isSecure ? "wss" : "ws";
        const httpProtocol = isSecure ? "https" : "http";
        const port = 8901; // Use the same port as defined in your FastAPI app
        const wsUrl = `${wsProtocol}://${host}:${port}/ws/v2`;
        const healthUrl = `${httpProtocol}://${host}:${port}/health`;

        // Connect to the WebSocket (using the new JSON endpoint)
        function connect() {
            socket = new WebSocket(wsUrl);

            socket.onopen = () => {
                messages.value.push({ text: "Connected to WebSocket.", type: "info" });
                scrollToBottom();
            };

            socket.onmessage = (event) => {
                let incoming;
                let messageType = "info";

                try {
                    incoming = JSON.parse(event.data);
                    if (incoming.videos && Array.isArray(incoming.videos)) {
                        videoList.value = incoming.videos;
                    }

                    if (incoming.error !== undefined) {
                        messageType = "error";
                    } else if (incoming.status !== undefined) {
                        messageType = "status";
                    }
                    messages.value.push({
                        text:
                            incoming.error !== undefined
                                ? incoming.error
                                : incoming.status !== undefined
                                    ? incoming.status
                                    : JSON.stringify(incoming),
                        type: messageType,
                    });
                } catch (e) {
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
                messages.value.push({
                    text: "WebSocket Error: " + (error.message || "Unknown error"),
                    type: "error",
                });
                scrollToBottom();
            };

            socket.onclose = () => {
                messages.value.push({
                    text: "WebSocket connection closed.",
                    type: "warning",
                });
                scrollToBottom();
                // Try to reconnect after 5 seconds.
                setTimeout(connect, 5000);
            };
        }

        // The updated sendCommand function builds a JSON payload based on the command entered.
        function sendCommand() {
            const cmdText = currentCommand.value.trim();
            if (!cmdText) return;
            let jsonPayload = null;

            // First, try to parse the input as JSON directly.
            try {
                jsonPayload = JSON.parse(cmdText);
            } catch (e) {
                // Otherwise, parse as a simple command string.
                // Split the command text into the command name and arguments.
                const parts = cmdText.split(" ");
                const command = parts[0].toLowerCase();
                const args = parts.slice(1).join(" ");

                switch (command) {
                    case "log":
                        let level = args ? args.toLowerCase() : "info";
                        jsonPayload = { command: "log", data: level };
                        break;
                    case "videolist":
                        jsonPayload = { command: "videolist" };
                        break;
                    case "video":
                        if (!args) {
                            messages.value.push({
                                text: "video command requires a video name",
                                type: "error",
                            });
                            return;
                        }
                        jsonPayload = { command: "video", data: args };
                        break;
                    case "stop":
                        jsonPayload = { command: "stop" };
                        break;
                    case "brightness":
                        const brightnessValue = parseInt(args, 10);
                        if (isNaN(brightnessValue)) {
                            messages.value.push({
                                text: "brightness command requires a numeric value",
                                type: "error",
                            });
                            return;
                        }
                        jsonPayload = { command: "brightness", data: brightnessValue };
                        break;
                    case "piano":
                        const tokens = args.trim().split(/\s+/);
                        if (tokens.length < 1) {
                            messages.value.push({
                                text: "Error: piano command requires at least a controller and window index",
                                type: "error",
                            });
                            return;
                        }

                        let controller, windowIdx;
                        if (tokens[0].includes(",")) {
                            const cw = tokens[0].split(",");
                            if (cw.length < 2) {
                                messages.value.push({
                                    text: "Error: piano command requires a controller and window index",
                                    type: "error",
                                });
                                return;
                            }
                            controller = parseInt(cw[0].trim(), 10);
                            windowIdx = parseInt(cw[1].trim(), 10);
                            tokens.shift(); // Remove the first token so that the remaining tokens can be processed.
                        } else {
                            if (tokens.length < 2) {
                                messages.value.push({
                                    text: "Error: piano command requires a controller and window index",
                                    type: "error",
                                });
                                return;
                            }
                            controller = parseInt(tokens[0].trim(), 10);
                            windowIdx = parseInt(tokens[1].trim(), 10);
                            tokens.splice(0, 2);
                        }

                        let persistent = false;
                        let color = [255, 255, 255];
                        tokens.forEach((token) => {
                            token = token.trim();
                            if (token.toLowerCase() === "persistent") {
                                persistent = true;
                            } else if (token.includes(",")) {
                                const colorParts = token.split(",");
                                if (colorParts.length !== 3) {
                                    messages.value.push({
                                        text: "Error: color must be in the format R,G,B",
                                        type: "error",
                                    });
                                    return;
                                }
                                color = colorParts.map((p) => parseInt(p.trim(), 10));
                            }
                        });

                        jsonPayload = {
                            command: "piano",
                            data: {
                                controller: controller,
                                window: windowIdx,
                                persistent: persistent,
                                color: color,
                            },
                        };
                        break;
                    case "christmas":
                        jsonPayload = { command: "christmas" };
                        break;
                    case "setall":
                        // Expect a 6-digit hex string, for example: "setall ffffff"
                        if (!args || args.length !== 6) {
                            messages.value.push({
                                text: "setall command requires a 6-digit hex color",
                                type: "error",
                            });
                            return;
                        }
                        jsonPayload = { command: "setall", data: args };
                        break;
                    case "update":
                        // Expect a comma-separated list of 400 hex strings.
                        const hexColors = args.split(",").map((s) => s.trim());
                        if (hexColors.length !== 400) {
                            messages.value.push({
                                text: "update command requires 400 comma-separated hex colors",
                                type: "error",
                            });
                            return;
                        }
                        jsonPayload = { command: "update", data: hexColors };
                        break;
                    case "difference":
                        // Expect pairs of values like: "difference (0), ffffff, (1), 000000"
                        const diffParts = args.split(",").map((s) => s.trim());
                        if (diffParts.length % 2 !== 0) {
                            messages.value.push({
                                text: "difference command requires pairs of values",
                                type: "error",
                            });
                            return;
                        }
                        const diffArray = [];
                        for (let i = 0; i < diffParts.length; i += 2) {
                            let index = diffParts[i].replace(/[()]/g, "");
                            let hex = diffParts[i + 1].replace(/[()]/g, "");
                            diffArray.push([index, hex]);
                        }
                        jsonPayload = { command: "difference", data: diffArray };
                        break;
                    default:
                        messages.value.push({
                            text: "Unknown command",
                            type: "error",
                        });
                        return;
                }
            }

            // Convert the command object to JSON and send it.
            const jsonMessage = JSON.stringify(jsonPayload);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(jsonMessage);
                messages.value.push({ text: "> " + jsonMessage, type: "command" });
                if (messages.value.length > MAX_MESSAGES) {
                    messages.value.shift();
                }
                currentCommand.value = "";
                filteredSuggestions.value = [];
                selectedSuggestionIndex.value = -1;
                scrollToBottom();
            } else {
                messages.value.push({
                    text: "WebSocket not connected.",
                    type: "error",
                });
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

            // Static suggestions from knownCommands.
            const staticSuggestions = knownCommands.filter(cmd =>
                cmd.toLowerCase().startsWith(input)
            );

            // Dynamic video suggestions: prefix each video name with "video ".
            const dynamicSuggestions = videoList.value
                .map(video => `video ${video}`)
                .filter(suggestion => suggestion.toLowerCase().startsWith(input));

            // Merge both arrays.
            // Optionally, you can remove duplicates by using a Set if needed.
            filteredSuggestions.value = staticSuggestions.concat(dynamicSuggestions);

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

        // Scroll the message window to the bottom
        function scrollToBottom() {
            nextTick(() => {
                const messagesContainer = document.querySelector(".messages");
                if (messagesContainer) {
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            });
        }

        onUpdated(() => nextTick(() => scrollToBottom()));

        // Perform an HTTP health check using the new API's /health endpoint.
        async function checkHealth() {
            try {
                const response = await fetch(healthUrl);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                const unreachable = Object.entries(data).filter(
                    ([ip, status]) => status !== "OK"
                );
                if (unreachable.length > 0) {
                    const ips = unreachable.map(([ip]) => ip).join(", ");
                    messages.value.push({
                        text: `Warning: The following devices are unreachable: ${ips}`,
                        type: "warning",
                    });
                    console.warn("Unreachable devices:", unreachable);
                } else {
                    messages.value.push({ text: "All devices are healthy.", type: "info" });
                }
            } catch (error) {
                messages.value.push({
                    text: `Error fetching health status: ${error.message}`,
                    type: "error",
                });
                console.error("Health check failed:", error);
            } finally {
                scrollToBottom();
            }
        }

        onMounted(() => {
            messages.value.push({
                text: "Type a command and press Enter to send it as JSON to the server.",
                type: "info",
            });
            messages.value.push({
                text: "Use the up and down arrow keys to select a suggestion and press Enter to choose it.",
                type: "info",
            });
            messages.value.push({
                text: "Known commands: " + knownCommands.join(", "),
                type: "info",
            });
            messages.value.push({ text: "Connecting to WebSocket...", type: "info" });
            connect();
            checkHealth();
            // Set up a periodic health check every 60 seconds
            healthCheckInterval = setInterval(checkHealth, 60000);
        });

        onUnmounted(() => {
            if (socket) {
                socket.close();
            }
            if (healthCheckInterval) {
                clearInterval(healthCheckInterval);
            }
        });

        function hideSuggestions() {
            filteredSuggestions.value = [];
            selectedSuggestionIndex.value = -1;
        }

        function pianoKey(controller, window) {
            const isPersistent = currentCommand.value.includes("persistent");
            currentCommand.value = `piano ${controller},${window} ${isPersistent ? "persistent" : ""}`.trim();
            sendCommand();
        }

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
            hideSuggestions,
            pianoKey,
        };
    },
}).mount("#app");
