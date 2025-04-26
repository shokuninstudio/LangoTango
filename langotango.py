import sys
import json
import os
from datetime import datetime
import requests
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QTextEdit, QPushButton, QToolBar, QTreeView, 
                             QComboBox, QLabel, QFileDialog, QSplitter, QMenu,
                             QMessageBox, QTreeWidget, QTreeWidgetItem, QInputDialog,
                             QFontComboBox, QColorDialog, QStyle, QDialog, QLineEdit,
                             QDialogButtonBox, QSizePolicy, QFormLayout)  # Add QSizePolicy here
from PySide6.QtGui import (QAction, QIcon, QTextCursor, QFont, QTextCharFormat, 
                         QColor, QTextListFormat, QKeySequence, QShortcut, QActionGroup, QTextBlockFormat, QPixmap, QTextDocumentWriter, QTextDocument, QSyntaxHighlighter)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QDir, QItemSelectionModel, QSize, QThread, QObject, QEvent, QByteArray
from PySide6.QtPrintSupport import QPrinter # Import QPrinter from QtPrintSupport
from spellchecker import SpellChecker
import re

# Define the file structure and document classes
class LangoTangoDocument:
    def __init__(self, name="Untitled", content=None, created=None, modified=None):
        self.name = name
        # Content is now a list of blocks, each block is a dict: {text, formatting, alignment}
        self.content = content if content is not None else []
        self.created = created or datetime.now().isoformat()
        self.modified = modified or self.created
        self.undo_stack = []
        self.redo_stack = []
        self.max_states = 50
        # Add initial state
        self.add_state(self.content)

    def add_state(self, content):
        # Deep copy to avoid mutation issues
        import copy
        self.undo_stack.append(copy.deepcopy(content))
        if len(self.undo_stack) > self.max_states:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if len(self.undo_stack) > 1:
            current = self.undo_stack.pop()
            self.redo_stack.append(current)
            if len(self.redo_stack) > self.max_states:
                self.redo_stack.pop(0)
            return self.undo_stack[-1]
        return self.content

    def redo(self):
        if self.redo_stack:
            current = self.redo_stack.pop()
            self.undo_stack.append(current)
            if len(self.undo_stack) > self.max_states:
                self.undo_stack.pop(0)
            return current
        return self.content

    def to_dict(self):
        return {
            "name": self.name,
            "content": self.content,
            "created": self.created,
            "modified": self.modified,
            "type": "document",
            "undo_stack": self.undo_stack,
            "redo_stack": self.redo_stack
        }

    @classmethod
    def from_dict(cls, data):
        doc = cls(
            name=data["name"],
            content=data["content"],
            created=data["created"],
            modified=data["modified"]
        )
        if "undo_stack" in data:
            doc.undo_stack = data["undo_stack"]
        if "redo_stack" in data:
            doc.redo_stack = data["redo_stack"]
        return doc
        
class LangoTangoFolder:
    def __init__(self, name="New Folder", items=None, created=None, modified=None):
        self.name = name
        self.items = items or []
        self.created = created or datetime.now().isoformat()
        self.modified = modified or self.created
        
    def to_dict(self):
        return {
            "name": self.name,
            "items": [item.to_dict() for item in self.items],
            "created": self.created,
            "modified": self.modified,
            "type": "folder"
        }
        
    @classmethod
    def from_dict(cls, data):
        folder = cls(
            name=data["name"],
            created=data["created"],
            modified=data["modified"]
        )
        
        for item_data in data["items"]:
            if item_data["type"] == "document":
                folder.items.append(LangoTangoDocument.from_dict(item_data))
            elif item_data["type"] == "folder":
                folder.items.append(LangoTangoFolder.from_dict(item_data))
                
        return folder

# Worker class for AI processing
class AIWorker(QObject):
    finished = Signal(str)
    error = Signal(str)
    
    def __init__(self, server, model, text, endpoints, character_prompt):
        super().__init__()
        self.server = server
        self.model = model
        self.text = text
        self.endpoints = endpoints
        self.character_prompt = character_prompt

    def process(self):
        try:
            if self.server == "Ollama":
                prompt = f"""
                {self.character_prompt}
                
                Here's what the user is currently working on:
                
                {self.text}
                
                Now respond with a brief, encouraging message:
                """
                
                response = requests.post(
                    self.endpoints["Ollama"],
                    json={"model": self.model, "prompt": prompt, "stream": False}
                )
                
                if response.status_code == 200:
                    ai_message = response.json().get("response", "")
                    self.finished.emit(ai_message)
                else:
                    self.error.emit(f"Error communicating with Ollama: {response.status_code}")
                    
            elif self.server == "LM Studio":
                messages = [
                    {"role": "system", "content": self.character_prompt},
                    {"role": "user", "content": f"Here's what I'm working on:\n\n{self.text}"}
                ]
                
                response = requests.post(
                    self.endpoints["LM Studio"],
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 100
                    }
                )
                
                if response.status_code == 200:
                    ai_message = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    self.finished.emit(ai_message)
                else:
                    self.error.emit(f"Error communicating with LM Studio: {response.status_code}")
                    
        except Exception as e:
            self.error.emit(str(e))

# Add this new worker class
class StreamingAIWorker(QThread):
    progress = Signal(str)  # For streaming updates
    finished = Signal()     # When complete
    error = Signal(str)     # For errors
    
    def __init__(self, server, model, text, instructions):
        super().__init__()
        self.server = server
        self.model = model 
        self.text = text
        self.instructions = instructions
        self.should_stop = False

    def run(self):
        try:
            if self.server == "Ollama":
                # Use the /api/chat endpoint for better instruction following
                response = requests.post(
                    "http://localhost:11434/api/chat", # Changed endpoint
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.instructions},
                            {"role": "user", "content": self.text}
                        ],
                        "stream": True,
                        # Explicitly add options, especially temperature
                        "options": {
                            "temperature": 0.1, # Lower temperature for less randomness
                            "num_ctx": 16384    # Ensure context window is considered
                        }
                    },
                    stream=True
                )

                for line in response.iter_lines():
                    # ... existing Ollama response handling ...
                    if self.should_stop:
                        break

                    if line:
                        try: # Add try-except for robustness
                            data = json.loads(line)
                            # Parse chat response format
                            if "message" in data and "content" in data["message"]:
                                self.progress.emit(data["message"]["content"])

                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            self.error.emit(f"Failed to decode JSON line: {line}")
                            continue # Skip malformed lines

            elif self.server == "LM Studio":
                # ... existing LM Studio code ...
                response = requests.post(
                    "http://localhost:1234/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.instructions},
                            {"role": "user", "content": self.text}
                        ],
                        "stream": True,
                        "max_tokens": 16384,
                        "temperature": 0.1 # Match temperature for comparison if desired
                    },
                    stream=True
                )

                for line in response.iter_lines():
                    if self.should_stop:
                        break

                    if line:
                        try:
                            # Remove 'data: ' prefix if present
                            line_str = line.decode('utf-8')
                            if line_str.startswith('data: '):
                                line_str = line_str[6:]

                            # Skip [DONE] message
                            if line_str.strip() == '[DONE]':
                                break

                            data = json.loads(line_str)
                            if 'choices' in data:
                                chunk = data['choices'][0]
                                if 'delta' in chunk and 'content' in chunk['delta']:
                                    content = chunk['delta']['content']
                                    if content:
                                        self.progress.emit(content)
                        except json.JSONDecodeError:
                            continue  # Skip malformed JSON lines

            if not self.should_stop:
                self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self.should_stop = True

# AI Commentary class to handle LLM interactions
class AICommentary(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_text = ""
        self.typing_timer = QTimer(self)
        self.typing_timer.setSingleShot(True)
        self.typing_timer.timeout.connect(self.analyze_text)
        self.model_endpoints = {
            "Ollama": "http://localhost:11434/api/generate",
            "LM Studio": "http://localhost:1234/v1/chat/completions"
        }
        self.worker_thread = None
        
        # Character templates
        self.characters = {
            "Japanese": """You are Japanese and you are a Japanese language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Japanese.""",
            
            "Mandarin": """You are Chinese and you are a Mandarin Chinese language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Mandarin Chinese.""",
            
            "Korean": """You are Korean and you are a Korean language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Korean.""",
            
            "Spanish": """You are Spanish and you are a Spanish language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Spanish.""",

            "Italian": """You are Italian and you are a Italian language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Italian.""",

            "French": """You are French and you are a French language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them French.""",
            
            "German": """You are FrGermanench and you are a German language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them German.""",

            "Portugese": """You are Portugese and you are a Portugese language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Portugese.""",

            "Dutch": """You are Dutch and you are a Dutch language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Dutch.""",

            "Greek": """You are Greek and you are a Greek language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Greek.""",

            "Hebrew": """You are Jewish and you are a Hebrew language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Hebrew.""",
            
            "Arabic": """You are Arab and you are a Arabic language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Arabic.""",

            "Hindi": """You are Hindustani and you are a Hindi language teacher. 
            You react to what the user is writing with encouragement. 
            If you see issues, be a critical teacher and correct them.
            Check spelling but accept slang. Do not repeat yourself often. Limit your responses to one sentence.
            You can also speak the same language as the user while you teach them Hindi."""
        }
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Server selection
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("LLM Server:"))
        self.server_combo = QComboBox()
        self.server_combo.addItems(["Ollama", "LM Studio"])
        self.server_combo.currentTextChanged.connect(self.on_server_changed)  # Changed from direct connection
        server_layout.addWidget(self.server_combo)
        layout.addLayout(server_layout)
        
        # Model selection
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)
        
        # Character selection with manage button
        char_layout = QHBoxLayout()
        char_layout.addWidget(QLabel("Language:"))
        self.char_combo = QComboBox()
        
        # Load any custom characters first
        self.load_custom_characters()
        
        # Add Japanese first, then the rest alphabetically
        self.char_combo.addItem("Japanese")
        other_chars = sorted([c for c in self.characters.keys() if c != "Japanese"])
        self.char_combo.addItems(other_chars)
        
        char_layout.addWidget(self.char_combo)
        
        # Change icon button to text button
        manage_chars_btn = QPushButton("Language Manager")
        manage_chars_btn.setToolTip("Add or remove custom languages")
        manage_chars_btn.clicked.connect(self.show_character_manager)
        char_layout.addWidget(manage_chars_btn)
        
        layout.addLayout(char_layout)
        
        # Refresh button for models
        refresh_btn = QPushButton("Refresh Models")
        refresh_btn.clicked.connect(self.fetch_available_models)
        layout.addWidget(refresh_btn)
        
        # Commentary output
        self.commentary = QTextEdit()
        self.commentary.setReadOnly(True)
        self.commentary.setPlaceholderText("AI commentary will appear here...")
        layout.addWidget(self.commentary)
        
        # Status bar for system messages
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.status_label)
        
        # Add buttons layout
        button_layout = QHBoxLayout()
        
        # Save and Clear buttons
        self.save_chat_btn = QPushButton("Save Chat")
        self.clear_chat_btn = QPushButton("Clear Chat")
        
        # Add buttons to layout
        button_layout.addWidget(self.save_chat_btn)
        button_layout.addWidget(self.clear_chat_btn)
        
        # Add button layout to main layout
        layout.addLayout(button_layout)
        
        # Connect button signals
        self.save_chat_btn.clicked.connect(self.save_chat)
        self.clear_chat_btn.clicked.connect(self.clear_chat)
        self.char_combo.currentTextChanged.connect(self.on_character_changed)
        
        # Initial greeting with default character
        self.current_character = self.char_combo.currentText()
        self.commentary.append(f"<b>{self.current_character}:</b> Loading...")

        # Fetch available models when initializing
        self.server_combo.currentTextChanged.connect(self.fetch_available_models)
        self.fetch_available_models()

    def fetch_available_models(self):
        """Fetch available models from the selected LLM server"""
        server = self.server_combo.currentText()
        self.model_combo.clear()
        
        try:
            if server == "Ollama":
                response = requests.get("http://localhost:11434/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [model["name"] for model in models]
                    self.model_combo.addItems(model_names)
                    self.status_label.setText("Connected to Ollama")
                else:
                    self.status_label.setText("Failed to connect to Ollama server")
            
            elif server == "LM Studio":
                response = requests.get("http://localhost:1234/v1/models")
                if response.status_code == 200:
                    models = response.json().get("data", [])
                    model_names = [model["id"] for model in models]
                    self.model_combo.addItems(model_names)
                    self.status_label.setText("Connected to LM Studio")
                else:
                    self.status_label.setText("Failed to connect to LM Studio server")
        
        except requests.exceptions.RequestException:
            self.status_label.setText(f"Failed to connect to {server}")

    def text_changed(self, text):
        """Called when the text editor content changes"""
        self.last_text = text
        # Reset the timer every time text changes
        self.typing_timer.start(1500)  # Wait 1.5 seconds after typing stops
    
    def get_random_quote(self):
        """Returns a random action movie quote"""
        import random
        return random.choice(self.action_quotes)
    
    def analyze_text(self):
        if not self.last_text or self.worker_thread is not None:
            return
            
        text_to_analyze = self.last_text[-500:] if len(self.last_text) > 500 else self.last_text
        
        server = self.server_combo.currentText()
        model = self.model_combo.currentText()
        character_prompt = self.characters.get(self.char_combo.currentText(), "")
        
        if not model:
            self.status_label.setText("No model selected. Please select a model.")
            return

        # Create worker and thread
        self.thread = QThread()
        self.worker = AIWorker(server, model, text_to_analyze, self.model_endpoints, character_prompt)
        self.worker.moveToThread(self.thread)

        # Connect signals
        self.thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.handle_response)
        self.worker.error.connect(self.handle_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.cleanup_thread)

        # Start processing
        self.thread.start()
        self.worker_thread = self.thread

    def handle_response(self, message):
        """Handle the AI response"""
        self.commentary.append(f"<b>{self.current_character}:</b> {message}")

    def handle_error(self, error_message):
        """Handle any errors"""
        self.status_label.setText(f"Error: {error_message}")

    def cleanup_thread(self):
        """Clean up the thread reference"""
        self.worker_thread = None
    
    def save_chat(self):
        """Save the chat history to a file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Chat History", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as file:
                    file.write(self.commentary.toPlainText())
                self.status_label.setText("Chat saved successfully")
            except Exception as e:
                self.status_label.setText(f"Failed to save chat: {str(e)}")
    
    def clear_chat(self):
        """Clear the chat history"""
        self.commentary.clear()
        self.commentary.append(f"<b>{self.current_character}:</b> Loading...")
        self.status_label.clear()

    def on_character_changed(self, character_name):
        """Handle character selection change"""
        self.current_character = character_name
        self.clear_chat()  # Clear existing chat
        self.commentary.append(f"<b>{character_name}:</b> Ready to assist you in my own unique way.")

    def update_character_combo(self):
        """Update character combo box while maintaining Japanese at top"""
        current = self.char_combo.currentText()
        self.char_combo.clear()
        
        # Always add Japanese first
        self.char_combo.addItem("Japanese")
        
        # Add others alphabetically
        other_chars = sorted([c for c in self.characters.keys() if c != "Japanese"])
        self.char_combo.addItems(other_chars)
        
        # Restore previous selection if it still exists
        index = self.char_combo.findText(current)
        if (index >= 0):
            self.char_combo.setCurrentIndex(index)
        else:
            # Default to Japanese if previous selection is gone
            self.char_combo.setCurrentText("Japanese")

    def show_character_manager(self):
        """Show dialog for managing custom languages"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Language Manager")
        dialog.setModal(True)
        dialog.setMinimumWidth(400)
    
        # Remove fixed size constraints and set minimum height
        dialog.setMinimumHeight(500)  # Add minimum height
    
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)  # Add spacing between elements
    
        # Character list with size policy
        char_list = QTreeWidget()
        char_list.setHeaderLabels(["Name", "Type"])
        char_list.setRootIsDecorated(False)
        char_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # Allow vertical expansion
        char_list.setColumnWidth(0, 250)  # Set width for name column
        layout.addWidget(char_list)
    
        # Populate list
        builtin_chars = ["Japanese", "Mandarin", "Korean", "Spanish", "Italian", "French", "German", "Portugese", "Dutch", "Greek", "Hebrew", "Arabic", "Hindi"]
                     
        for name, prompt in self.characters.items():
            item = QTreeWidgetItem(char_list)
            item.setText(0, name)
            is_builtin = name in builtin_chars
            item.setText(1, "Built-in" if is_builtin else "Custom")
            if not is_builtin:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
    
        # Buttons layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)  # Add spacing between buttons
    
        add_btn = QPushButton("Add Character")
        remove_btn = QPushButton("Remove Character")
        remove_btn.setEnabled(False)  # Initially disabled
        close_btn = QPushButton("Close")
    
        button_layout.addWidget(add_btn)
        button_layout.addWidget(remove_btn)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        def on_selection_changed():
            selected = char_list.selectedItems()
            if selected:
                remove_btn.setEnabled(selected[0].text(1) == "Custom")
        
        def add_new_character():
            add_dialog = QDialog(dialog)
            add_dialog.setWindowTitle("Add New Character")
            add_layout = QVBoxLayout(add_dialog)
            
            # Name input
            name_layout = QHBoxLayout()
            name_layout.addWidget(QLabel("Name:"))
            name_input = QLineEdit()
            name_layout.addWidget(name_input)
            add_layout.addLayout(name_layout)
            
            # Description input
            add_layout.addWidget(QLabel("Character Description:"))
            desc_input = QTextEdit()
            desc_input.setPlaceholderText("Describe the character's personality, tone, and behavior...")
            add_layout.addWidget(desc_input)
            
            # Dialog buttons
            btn_box = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                Qt.Horizontal, add_dialog
            )
            btn_box.accepted.connect(add_dialog.accept)
            btn_box.rejected.connect(add_dialog.reject)
            add_layout.addWidget(btn_box)
            
            if add_dialog.exec() == QDialog.Accepted:
                name = name_input.text().strip()
                desc = desc_input.toPlainText().strip()
                
                if name and desc:
                    # Add to characters
                    self.characters[name] = desc
                    
                    # Add to list
                    item = QTreeWidgetItem(char_list)
                    item.setText(0, name)
                    item.setText(1, "Custom")
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    
                    # Save changes
                    self.save_custom_characters()
                    self.update_character_combo()
        
        def remove_character():
            selected = char_list.selectedItems()
            if selected and selected[0].text(1) == "Custom":
                name = selected[0].text(0)
                if name in self.characters:
                    del self.characters[name]
                    char_list.takeTopLevelItem(char_list.indexOfTopLevelItem(selected[0]))
                    self.save_custom_characters()
                    self.update_character_combo()
        
        # Connect signals
        char_list.itemSelectionChanged.connect(on_selection_changed)
        add_btn.clicked.connect(add_new_character)
        remove_btn.clicked.connect(remove_character)
        close_btn.clicked.connect(dialog.close)
        
        dialog.exec()

    def get_characters_path(self):
        """Get path to custom characters file"""
        if sys.platform == 'darwin':  # macOS
            settings_dir = Path.home() / 'Library' / 'Application Support' / 'LangoTango'
        elif sys.platform == 'win32':  # Windows
            settings_dir = Path.home() / 'AppData' / 'Local' / 'LangoTango'
        else:  # Linux and others
            settings_dir = Path.home() / '.config' / 'LangoTango'
        
        settings_dir.mkdir(parents=True, exist_ok=True)
        return settings_dir / 'custom_characters.json'

    def load_custom_characters(self):
        """Load custom characters from file"""
        try:
            path = self.get_characters_path()
            if path.exists():
                with open(path, 'r') as f:
                    custom_chars = json.load(f)
                    self.characters.update(custom_chars)
        except Exception as e:
            print(f"Error loading custom characters: {e}")

    def save_custom_characters(self):
        """Save custom characters to file"""
        try:
            # Only save custom characters (not built-in ones)
            builtin_chars = ["Japanese", "Mandarin", "Korean", "Spanish", "Italian", "French", "German", "Portugese", "Dutch", "Greek", "Hebrew", "Arabic", "Hindi"]
            
            custom_chars = {name: prompt for name, prompt in self.characters.items() 
                           if name not in builtin_chars}
            
            with open(self.get_characters_path(), 'w') as f:
                json.dump(custom_chars, f, indent=2)
        except Exception as e:
            print(f"Error saving custom characters: {e}")

    # Add to the AICommentary class
    def on_server_changed(self, server):
        """Handle server selection change"""
        # Clean up any existing models
        self.cleanup_resources()
        
        # Fetch models for the new server  
        self.fetch_available_models()

    def cleanup_resources(self):
        """Clean up resources to prevent memory leaks"""
        # Clean up worker thread if running
        if hasattr(self, 'worker_thread') and self.worker_thread is not None:
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
        
        # Request Python garbage collection
        import gc
        gc.collect()

# Add ProjectDialog class
class ProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LangoTango")
        self.setFixedSize(400, 150)
        
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("You never did know when to quit! Let's get started.")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        # Buttons
        btn_layout = QVBoxLayout()
        
        self.new_project_btn = QPushButton("New Project")
        self.open_project_btn = QPushButton("Open Project")
        
        btn_layout.addWidget(self.new_project_btn)
        btn_layout.addWidget(self.open_project_btn)
        
        layout.addLayout(btn_layout)
        
        # Connect buttons
        self.new_project_btn.clicked.connect(self.create_new_project)
        self.open_project_btn.clicked.connect(self.load_existing_project)
        
        self.project_path = None
        self.project_name = None
        
    def create_new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if ok and name:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Save Project", f"{name}.lango", "LangoTango Files (*.lango)"
            )
            if file_path:
                self.project_path = file_path
                self.project_name = name
                self.accept()
    
    def load_existing_project(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "LangoTango Files (*.lango)"
        )
        if file_path:
            self.project_path = file_path
            self.accept()

# Main application window
class LangoTangoWordProcessor(QMainWindow):
    def __init__(self):  # Remove splash parameter
        super().__init__()
        self.last_format = QTextCharFormat()
        self.last_alignment = Qt.AlignLeft
        
        # Set up initial document and file path
        self.current_document = LangoTangoDocument()
        self.current_file_path = None
        self.root_folder = LangoTangoFolder("My Documents")
        self.research_folder = LangoTangoFolder("Research")  # Create research folder
        self.trash_folder = LangoTangoFolder("Trash")  # Create trash folder
        
        # Set up word count update timer
        self.word_count_timer = QTimer(self)
        self.word_count_timer.timeout.connect(self.update_word_count)
        self.word_count_timer.start(2000)
        
        # Set up auto-save timer
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.timeout.connect(self.auto_save)
        self.auto_save_timer.setInterval(180000)  # 180 seconds
        
        # Initialize UI first
        self.setup_ui()
        self.setup_keyboard_shortcuts()  # Add this line
        self.setup_connections()
        self.load_window_settings()
        self.setup_status_bar()
        
        self.setWindowTitle("LangoTango")

    def setup_keyboard_shortcuts(self):
        """Set up keyboard shortcuts for common operations"""
        # Project operations
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_document)  # Cmd/Ctrl + O 
        QShortcut(QKeySequence.StandardKey.Save, self, self.save_document)  # Cmd/Ctrl + S
        
        # Import/Export
        QShortcut(QKeySequence("Ctrl+M"), self, self.import_text)  # Cmd/Ctrl + M
        QShortcut(QKeySequence("Ctrl+E"), self, self.export_text)  # Cmd/Ctrl + E
        
        # New items
        QShortcut(QKeySequence("Ctrl+N"), self, lambda: self.create_new_folder())  # Cmd/Ctrl + F
        QShortcut(QKeySequence("Ctrl+D"), self, lambda: self.create_new_file())    # Cmd/Ctrl + D

        # Add Find/Replace shortcut
        QShortcut(QKeySequence.StandardKey.Find, self, self.open_find_replace_dialog)  # Cmd/Ctrl + F

        # Add highlight shortcut
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: self.format_text("highlight"))  # Cmd/Ctrl + L

        # Add window close shortcut (Cmd+W on macOS, Ctrl+W on Windows/Linux)
        close_shortcut = QShortcut(QKeySequence.StandardKey.Close, self)
        close_shortcut.activated.connect(self.close)

        # Text Alignment formatting shortcuts
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.format_text("alignment", Qt.AlignLeft))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.format_text("alignment", Qt.AlignCenter))
        QShortcut(QKeySequence("Ctrl+3"), self, lambda: self.format_text("alignment", Qt.AlignRight))
        QShortcut(QKeySequence("Ctrl+4"), self, lambda: self.format_text("alignment", Qt.AlignJustify))
        
        # Add undo/redo shortcuts
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo_document)
        
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.redo_shortcut.activated.connect(self.redo_document)

    def get_settings_path(self):
        """Get platform-specific settings directory and file path"""
        if sys.platform == 'darwin':  # macOS
            settings_dir = Path.home() / 'Library' / 'Application Support' / 'LangoTango'
        elif sys.platform == 'win32':  # Windows
            settings_dir = Path.home() / 'AppData' / 'Local' / 'LangoTango'
        else:  # Linux and others
            settings_dir = Path.home() / '.config' / 'LangoTango'
        
        settings_dir.mkdir(parents=True, exist_ok=True)
        return settings_dir / 'settings.json'

    def save_window_settings(self):
        """Save window geometry, state and preferences to JSON file"""
        settings = {
            'pos_x': self.pos().x(),
            'pos_y': self.pos().y(),
            'width': self.width(),
            'height': self.height(),
            'is_maximized': self.isMaximized(),
            'default_character': self.ai_panel.char_combo.currentText(),
            'toolbar_area': int(self.toolBarArea(self.toolbar).value),
            # Fix: convert QByteArray to bytes then decode
            'splitter_state': bytes(self.splitter.saveState().toBase64()).decode(),
            # Save LLM server and model preferences
            'llm_server': self.ai_panel.server_combo.currentText(),
            'ollama_model': self.ai_panel.model_combo.currentText() if self.ai_panel.server_combo.currentText() == "Ollama" else "",
            'lm_studio_model': self.ai_panel.model_combo.currentText() if self.ai_panel.server_combo.currentText() == "LM Studio" else ""
        }
        
        try:
            with open(self.get_settings_path(), 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def load_window_settings(self):
        """Load and apply saved window geometry, state and preferences"""
        try:
            with open(self.get_settings_path(), 'r') as f:
                settings = json.load(f)
                
            if settings.get('is_maximized'):
                self.showMaximized()
            else:
                self.resize(settings.get('width', 1200), 
                           settings.get('height', 800))
                self.move(settings.get('pos_x', 0), 
                         settings.get('pos_y', 0))

            # Load default character if set
            default_character = settings.get('default_character')
            if default_character and hasattr(self, 'ai_panel'):
                index = self.ai_panel.char_combo.findText(default_character)
                if index >= 0:
                    self.ai_panel.char_combo.setCurrentIndex(index)
                    self.ai_panel.current_character = default_character

            # Load LLM server and model preferences
            if hasattr(self, 'ai_panel'):
                # First set the server - this will trigger model fetch
                saved_server = settings.get('llm_server')
                if saved_server:
                    self.ai_panel.server_combo.setCurrentText(saved_server)
                    
                # Wait briefly for models to load then select the saved model
                QTimer.singleShot(1000, lambda: self.select_saved_model(settings))

            # Restore toolbar position
            toolbar_area = settings.get('toolbar_area')
            if (toolbar_area is not None):
                self.addToolBar(Qt.ToolBarArea(toolbar_area), self.toolbar)

            # Restore splitter state
            splitter_state = settings.get('splitter_state')
            if splitter_state:
                self.splitter.restoreState(QByteArray.fromBase64(splitter_state.encode()))
                         
        except FileNotFoundError:
            # Use default size if no settings file exists
            self.resize(1200, 800)
        except Exception as e:
            print(f"Error loading settings: {e}")

    def select_saved_model(self, settings):
        """Select the saved model based on current server"""
        if not hasattr(self, 'ai_panel'):
            return
            
        current_server = self.ai_panel.server_combo.currentText()
        model_key = 'ollama_model' if current_server == "Ollama" else 'lm_studio_model'
        saved_model = settings.get(model_key)
        
        if saved_model and self.ai_panel.model_combo.count() > 0:
            # First check if the model exists
            index = self.ai_panel.model_combo.findText(saved_model)
            if index >= 0:
                self.ai_panel.model_combo.setCurrentIndex(index)

    def cleanup_threads(self):
        """Clean up any running threads"""
        # Cleanup AI panel threads
        if hasattr(self, 'ai_panel'):
            if hasattr(self.ai_panel, 'worker_thread'):
                if self.ai_panel.worker_thread is not None:
                    self.ai_panel.worker_thread.quit()
                    self.ai_panel.worker_thread.wait()

    def closeEvent(self, event):
        """Handle window close event"""
        # Clean up threads first
        self.cleanup_threads()
        
        # Stop timers
        self.word_count_timer.stop()
        self.auto_save_timer.stop()
        
        # Save settings
        self.save_window_settings()
        
        # Final save before closing
        if self.current_file_path:
            self.save_to_file(self.current_file_path)
        
        # Accept the close event
        event.accept()

    def initialize_project(self):
        """Initialize new project without showing dialog"""
        # Create initial empty document with hello message
        self.root_folder = LangoTangoFolder("My Documents")
        initial_doc = LangoTangoDocument(
            "Hello.lango", 
            [{
                'text': "It takes two to LangoTango!",
                'font_family': 'Courier New',
                'font_size': 12,
                'bold': False,
                'italic': False,
                'underline': False,
                'highlight': False,
                'alignment': int(Qt.AlignLeft)
            }]
        )
        self.root_folder.items.append(initial_doc)
        self.current_document = initial_doc
        
        # Set up empty folders
        self.research_folder = LangoTangoFolder("Research")
        self.trash_folder = LangoTangoFolder("Trash")
        
        # Update UI
        json_to_qtextedit(initial_doc.content, self.text_editor)
        self.update_file_tree()

        # Select first document and start auto-save
        self.select_first_document()
        self.auto_save_timer.start()
        
        return True

    def select_first_document(self):
        """Select the first available document in the file tree"""
        def find_first_document(item):
            # Check if current item is a document
            data = item.data(0, Qt.UserRole)
            if isinstance(data, LangoTangoDocument):
                return item
                
            # If not, check children
            for i in range(item.childCount()):
                child = item.child(i)
                result = find_first_document(child)
                if result:
                    return result
            return None
            
        # Start with root item
        root_item = self.file_tree.topLevelItem(0)
        if root_item:
            first_doc = find_first_document(root_item)
            if first_doc:
                # Select the document in tree and load it
                self.file_tree.setCurrentItem(first_doc)
                data = first_doc.data(0, Qt.UserRole)
                self.current_document = data
                json_to_qtextedit(data.content, self.text_editor)
                return True
                
        return False

    def text_editor_clicked(self):
        """Handle clicks in the text editor"""
        if not self.current_document:
            # If no document is selected, select the first available one
            if not self.select_first_document():
                QMessageBox.warning(
                    self,
                    "No Document Selected",
                    "Please select or create a document in the file tree before editing."
                )
                self.text_editor.setReadOnly(True)
                return
        self.text_editor.setReadOnly(False)

    def create_new_project(self, name, file_path):
        """Create a new project with initial structure"""
        self.root_folder = LangoTangoFolder(name)
        # Create an initial empty document
        initial_doc = LangoTangoDocument(f"New document.lango", "Some damn fool accused you of being the best. Prove it!")
        self.root_folder.items.append(initial_doc)
        self.current_document = initial_doc
        json_to_qtextedit(initial_doc.content, self.text_editor)  # Set initial content
        
        # Save the project
        self.save_to_file(file_path)
        
        # Update the UI
        self.update_file_tree()
        self.setWindowTitle(f"LangoTango - {name}")

    def open_project(self, file_path):
        """Load an existing project"""
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
                self.load_workspace(data)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open project: {str(e)}")

    def setup_ui(self):
        # Main layout with splitter
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_layout = QHBoxLayout(self.central_widget)
        
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(3)
        main_layout.addWidget(self.splitter)
        
        # File browser panel
        self.file_panel = QWidget()
        file_layout = QVBoxLayout(self.file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        
        # File tree with icons
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabel("Files")
        self.file_tree.setIconSize(QSize(16, 16))
        
        # Enable drag and drop
        self.file_tree.setDragEnabled(True)
        self.file_tree.setAcceptDrops(True)
        self.file_tree.setDragDropMode(QTreeWidget.InternalMove)
        self.file_tree.setDropIndicatorShown(True)
        
        # Connect drag and drop signal
        self.file_tree.dropEvent = self.tree_drop_event
        
        # Get standard icons from QStyle
        style = self.style()
        self.folder_icon = style.standardIcon(QStyle.SP_DirIcon)
        self.file_icon = style.standardIcon(QStyle.SP_FileIcon)
        self.research_icon = style.standardIcon(QStyle.SP_DriveNetIcon)  # Research folder icon
        self.trash_icon = style.standardIcon(QStyle.SP_TrashIcon)
        
        file_layout.addWidget(self.file_tree)
        
        # File actions
        file_buttons = QHBoxLayout()
        self.new_file_btn = QPushButton("New File")
        self.new_folder_btn = QPushButton("New Folder")
        file_buttons.addWidget(self.new_file_btn)
        file_buttons.addWidget(self.new_folder_btn)
        file_layout.addLayout(file_buttons)
        
        self.splitter.addWidget(self.file_panel)
        
        # Editor panel
        self.editor_panel = QWidget()
        editor_layout = QVBoxLayout(self.editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        
        # Text editor
        self.setup_text_editor()
        editor_layout.addWidget(self.text_editor)
        self.splitter.addWidget(self.editor_panel)
        
        # Now create toolbar after text_editor exists
        self.setup_toolbar()
        
        # AI Commentary panel
        self.ai_panel = AICommentary()
        self.splitter.addWidget(self.ai_panel)
        
        # Set splitter sizes
        self.splitter.setSizes([200, 600, 300])
        
        # Populate file tree with root folder
        self.update_file_tree()
    
    def setup_text_editor(self):
        """Setup the text editor with fixed formatting and spell checking"""
        # Use SpellCheckTextEdit instead of QTextEdit
        self.text_editor = SpellCheckTextEdit(spell_checker=self, parent=self)
        self.text_editor.setPlaceholderText("It takes two to LangoTango!")
        
        # Set up default document formatting with fixed font
        document = self.text_editor.document()
        default_font = QFont("Courier New", 12)
        document.setDefaultFont(default_font)
        
        # Set up default text option
        text_option = document.defaultTextOption()
        text_option.setAlignment(Qt.AlignLeft)
        document.setDefaultTextOption(text_option)
        
        # Add spell check highlighter
        self.highlighter = SpellCheckHighlighter(self.text_editor.document())
        
        # Connect document change signal
        self.text_editor.textChanged.connect(self.document_changed)
        
        # Install event filter for paste events ONLY
        self.text_editor.installEventFilter(self)
        
        # Initialize list variables
        self.list_active = False
        self.current_list_marker = ""

    def eventFilter(self, obj, event):
        """Handle key events for lists and paste events to preserve formatting but enforce font"""
        if obj == self.text_editor and event.type() == QEvent.Type.KeyPress:
            # Handle Enter key for consistent line breaks
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                cursor = self.text_editor.textCursor()
                cursor.beginEditBlock()

                # Insert a new block with the same formatting as the current block
                current_block_format = cursor.blockFormat()
                cursor.insertBlock(current_block_format)

                cursor.endEditBlock()
                return True
            
            # Handle paste events
            if (event.key() == Qt.Key_V and 
                event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
                
                # Instead of default paste, get plain text from clipboard
                clipboard = QApplication.clipboard()
                text = clipboard.text()  # Get as plain text
            
                # Insert plain text with editor's default font
                cursor = self.text_editor.textCursor()
                format = QTextCharFormat()
                format.setFont(QFont("Courier New", 12))
                cursor.insertText(text, format)
                
                return True
                
            # Handle Enter key for list continuation
            elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                cursor = self.text_editor.textCursor()
                
                # Store current block text before Enter creates a new line
                current_line = cursor.block().text()
                
                # Let standard Enter processing happen first
                self.text_editor.keyPressEvent(event)
                
                # Check if last Enter was double-Enter to exit list mode
                if self.list_active and current_line.strip() == self.current_list_marker.strip():
                    self.list_active = False
                    return True
                    
                # Check for list markers
                marker_type, marker_value, marker_format = self.parse_list_marker(current_line)
                if marker_type:
                    # We found a list marker
                    self.list_active = True
                    next_marker = self.get_next_marker(marker_type, marker_value, marker_format)
                    self.current_list_marker = next_marker
                    
                    # Insert the next marker
                    cursor = self.text_editor.textCursor()
                    cursor.insertText(next_marker + " ")
                    return True
                    
                # Not in list mode and no marker found, reset list tracking
                self.list_active = False
                
                return False
                
            # Handle Backspace to exit list mode
            elif event.key() == Qt.Key_Backspace and self.list_active:
                cursor = self.text_editor.textCursor()
                pos_in_block = cursor.positionInBlock()
                current_line = cursor.block().text()
                
                marker_type, _, _ = self.parse_list_marker(current_line)
                if marker_type and pos_in_block <= len(current_line.lstrip()) + 1:
                    # Allow the backspace, but exit list mode if we're at the marker
                    self.text_editor.keyPressEvent(event)
                    self.list_active = False
                    return True
                    
        return super().eventFilter(obj, event)

    def parse_list_marker(self, text):
        """Parse list marker from text and return (type, value, format)"""
        import re
        
        # Check for ordered list markers (1., 1), etc.)
        match = re.match(r'^\s*(\d+)([\.\)])\s*', text)
        if match:
            return ('numeric', int(match.group(1)), match.group(2))
            
        # Check for uppercase letter markers (A., A))
        match = re.match(r'^\s*([A-Z])([\.\)])\s*', text)
        if match:
            return ('uppercase', match.group(1), match.group(2))
            
        # Check for lowercase letter markers (a., a))
        match = re.match(r'^\s*([a-z])([\.\)])\s*', text)
        if match:
            return ('lowercase', match.group(1), match.group(2))
            
        return (None, None, None)

    def get_next_marker(self, marker_type, value, format='.'):
        """Get the next marker in sequence with the same format"""
        if marker_type == 'numeric':
            return f"{value + 1}{format}"
            
        elif marker_type == 'uppercase':
            # Convert letter to ASCII code, increment, convert back
            next_letter = chr(ord(value) + 1)
            if next_letter > 'Z':
                next_letter = 'A'  # Wrap around
            return f"{next_letter}{format}"
            
        elif marker_type == 'lowercase':
            next_letter = chr(ord(value) + 1)
            if next_letter > 'z':
                next_letter = 'a'  # Wrap around
            return f"{next_letter}{format}"

    def document_changed(self):
        """Handle document changes"""
        if self.current_document is not None:
            content = qtextedit_to_json(self.text_editor)
            if content != self.current_document.content:
                self.current_document.content = content
                self.current_document.modified = datetime.now().isoformat()
                # Add new state to undo stack
                self.current_document.add_state(content)
                
                # Update undo/redo availability
                self.undo_shortcut.setEnabled(len(self.current_document.undo_stack) > 1)
                self.redo_shortcut.setEnabled(len(self.current_document.redo_stack) > 0)

    def cursor_position_changed(self):
        """Update UI when cursor position changes"""
        cursor = self.text_editor.textCursor()
        char_format = cursor.charFormat()
        block_format = cursor.blockFormat()
        
        # Update style buttons
        self.bold_action.setChecked(char_format.font().bold())
        self.italic_action.setChecked(char_format.font().italic())
        self.underline_action.setChecked(char_format.font().underline())
        
        # Update highlight button state
        self.highlight_action.setChecked(char_format.background().color() == QColor(255, 255, 0))
        
        # Update alignment buttons
        alignment = block_format.alignment()
        for action, align in [(self.align_left, Qt.AlignLeft),
                             (self.align_center, Qt.AlignCenter),
                             (self.align_right, Qt.AlignRight),
                             (self.align_justify, Qt.AlignJustify)]:
            action.setChecked(alignment == align)

    def format_text(self, format_type, value=None):
        """Apply formatting using standard QTextCursor operations"""
        cursor = self.text_editor.textCursor()
        
        if format_type == "highlight":
            cursor.beginEditBlock()

            # Get the actual selection range regardless of direction
            start = min(cursor.position(), cursor.anchor())
            end = max(cursor.position(), cursor.anchor())
        
            # Create a new cursor with normalized selection (left to right)
            normalized_cursor = QTextCursor(cursor)
            normalized_cursor.setPosition(start)
            normalized_cursor.setPosition(end, QTextCursor.KeepAnchor)

            char_format = normalized_cursor.charFormat()
            
            # Toggle highlight - use the same color for checking and applying
            highlight_color = QColor(175, 180, 65)  # Change to your desired color
            
            if char_format.background().color() == highlight_color:
                # Remove highlight by setting a transparent/no background
                new_format = QTextCharFormat()
                new_format.setBackground(Qt.GlobalColor.transparent)
                normalized_cursor.mergeCharFormat(new_format)
                self.highlight_action.setChecked(False)
            else:
                # Add highlight with the same color we check against
                new_format = QTextCharFormat()
                new_format.setBackground(highlight_color)
                normalized_cursor.mergeCharFormat(new_format)
                self.highlight_action.setChecked(True)
                
            cursor.endEditBlock()
        
        elif format_type == "font":
            cursor.beginEditBlock()
            if cursor.hasSelection():
                pos = cursor.position()
                anchor = cursor.anchor()
                cursor.setPosition(min(pos, anchor))
                cursor.setPosition(max(pos, anchor), QTextCursor.KeepAnchor)
            char_format = cursor.charFormat()
            char_format.setFont(value)
            cursor.mergeCharFormat(char_format)
            cursor.endEditBlock()
        
        elif format_type == "style":
            cursor.beginEditBlock()
            char_format = cursor.charFormat()
            font = char_format.font()
            
            if value == "bold":
                font.setBold(not font.bold())
            elif value == "italic":
                font.setItalic(not font.italic())
            elif value == "underline":
                font.setUnderline(not font.underline())
                
            char_format.setFont(font)
            cursor.mergeCharFormat(char_format)
            cursor.endEditBlock()
        
        elif format_type == "alignment":
            cursor.beginEditBlock()
            block_format = cursor.blockFormat()
            block_format.setAlignment(value)
            cursor.setBlockFormat(block_format)
            cursor.endEditBlock()
        
        self.text_editor.setFocus()

    def setup_toolbar(self):
        # Create toolbar
        self.toolbar = self.addToolBar("Formatting") # Changed name for clarity
        
        # Set icon size for toolbar items
        self.toolbar.setIconSize(QSize(16, 16)) # Increased icon size slightly
        
        # Set text size using stylesheet (if needed, but icons are primary now)
        # self.toolbar.setStyleSheet("""
        #     QToolBar { font-size: 12px; }
        #     QToolButton { font-size: 12px; }
        # """)
        
        # --- File Operations ---
        self.open_project_btn = QPushButton("Open Project")
        self.save_project_btn = QPushButton("Save Project")
        self.new_window_btn = QPushButton("New Window")
        self.import_text_btn = QPushButton("Import Text")
        self.export_text_btn = QPushButton("Export Text")
        
        self.toolbar.addWidget(self.open_project_btn)
        self.toolbar.addWidget(self.save_project_btn)
        self.toolbar.addWidget(self.new_window_btn)
        self.toolbar.addWidget(self.import_text_btn)
        self.toolbar.addWidget(self.export_text_btn)

        # --- Separator ---
        self.toolbar.addSeparator()

        # --- Text Styles ---
        style = self.style()
        self.bold_action = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Bold", self) # Placeholder, use real icon
        self.bold_action.setShortcut(QKeySequence.Bold)
        self.bold_action.setCheckable(True)
        self.bold_action.triggered.connect(lambda: self.format_text("style", "bold"))
        # Use QStyle standard icons if available, or load custom ones
        self.bold_action.setIcon(QIcon.fromTheme("format-text-bold", style.standardIcon(QStyle.SP_DialogOkButton))) # Example fallback

        self.italic_action = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Italic", self)
        self.italic_action.setShortcut(QKeySequence.Italic)
        self.italic_action.setCheckable(True)
        self.italic_action.triggered.connect(lambda: self.format_text("style", "italic"))
        self.italic_action.setIcon(QIcon.fromTheme("format-text-italic", style.standardIcon(QStyle.SP_DialogOkButton)))

        self.underline_action = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Underline", self)
        self.underline_action.setShortcut(QKeySequence.Underline)
        self.underline_action.setCheckable(True)
        self.underline_action.triggered.connect(lambda: self.format_text("style", "underline"))
        self.underline_action.setIcon(QIcon.fromTheme("format-text-underline", style.standardIcon(QStyle.SP_DialogOkButton)))

        self.highlight_action = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Highlight", self)
        self.highlight_action.setCheckable(True)
        self.highlight_action.triggered.connect(lambda: self.format_text("highlight"))
        self.highlight_action.setIcon(QIcon.fromTheme("format-text-highlight", style.standardIcon(QStyle.SP_DialogResetButton)))

        self.toolbar.addAction(self.bold_action)
        self.toolbar.addAction(self.italic_action)
        self.toolbar.addAction(self.underline_action)
        self.toolbar.addAction(self.highlight_action)

        # --- Separator ---
        self.toolbar.addSeparator()

        # --- Text Alignment ---
        self.align_group = QActionGroup(self)
        self.align_left = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Align Left", self)
        self.align_left.setCheckable(True)
        self.align_left.setChecked(True) # Default alignment
        self.align_left.triggered.connect(lambda: self.format_text("alignment", Qt.AlignLeft))
        self.align_left.setIcon(QIcon.fromTheme("format-justify-left", style.standardIcon(QStyle.SP_ArrowLeft)))
        self.align_group.addAction(self.align_left)

        self.align_center = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Align Center", self)
        self.align_center.setCheckable(True)
        self.align_center.triggered.connect(lambda: self.format_text("alignment", Qt.AlignCenter))
        self.align_center.setIcon(QIcon.fromTheme("format-justify-center", style.standardIcon(QStyle.SP_DialogYesButton))) # Placeholder
        self.align_group.addAction(self.align_center)

        self.align_right = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Align Right", self)
        self.align_right.setCheckable(True)
        self.align_right.triggered.connect(lambda: self.format_text("alignment", Qt.AlignRight))
        self.align_right.setIcon(QIcon.fromTheme("format-justify-right", style.standardIcon(QStyle.SP_ArrowRight)))
        self.align_group.addAction(self.align_right)

        # Create justify action but don't add it to toolbar because AI generated text will not justify (keep for shortcut only)
        self.align_justify = QAction(style.standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Align Justify", self)
        self.align_justify.setCheckable(True)
        self.align_justify.triggered.connect(lambda: self.format_text("alignment", Qt.AlignJustify))
        self.align_justify.setIcon(QIcon.fromTheme("format-justify-fill", style.standardIcon(QStyle.SP_FileDialogDetailedView)))
        self.align_group.addAction(self.align_justify)  # Add to group but not toolbar

        # Add only visible alignment buttons to toolbar
        self.toolbar.addAction(self.align_left)
        self.toolbar.addAction(self.align_center)
        self.toolbar.addAction(self.align_right)
        # self.toolbar.addAction(self.align_justify)  # Comment out this line because AI generated text will not justify

        # --- Separator ---
        self.toolbar.addSeparator()

        # --- Document Actions ---
        self.find_replace_btn = QPushButton("Find/Replace")
        self.toolbar.addWidget(self.find_replace_btn)
        self.find_replace_btn.clicked.connect(self.open_find_replace_dialog)

        self.query_btn = QPushButton("Query")
        self.toolbar.addWidget(self.query_btn)
        self.query_btn.clicked.connect(self.open_query_dialog)

        self.compile_btn = QPushButton("Compile")
        self.toolbar.addWidget(self.compile_btn)
        self.compile_btn.clicked.connect(self.compile_project)

        # --- Spacer and Search ---
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        
        self.search_field = ProjectSearchField(main_window=self)
        self.toolbar.addWidget(self.search_field)
        
        right_spacer = QWidget()
        right_spacer.setFixedWidth(10)
        self.toolbar.addWidget(right_spacer)

        # --- Connect Button Signals (File Ops) ---
        self.open_project_btn.clicked.connect(self.open_document)
        self.save_project_btn.clicked.connect(self.save_document)
        self.import_text_btn.clicked.connect(self.import_text)
        self.export_text_btn.clicked.connect(self.export_text)

        # Connect cursor position changes to update toolbar state
        self.text_editor.cursorPositionChanged.connect(self.cursor_position_changed)

    def import_text(self):
        """Import text from a file into the current editor"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Text", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as file:
                    text = file.read()
                    # Create text cursor and set default character format
                    cursor = self.text_editor.textCursor()
                    char_format = QTextCharFormat()
                    char_format.setFont(QFont("Courier New", 12))
                    
                    # Insert text with default format
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.Start)
                    cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
                    cursor.insertText(text, char_format)
                    cursor.endEditBlock()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import text: {str(e)}")

    def export_text(self):
        """Export text with formatting as ODT, PDF, Markdown, plain text, or FDX"""
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Export Text")
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        
        filters = [
            "OpenDocument Text (*.odt)",
            "PDF Document (*.pdf)",
            "Markdown (*.md)",
            "Plain Text (*.txt)",
            "Final Draft (*.fdx)"  # Add FDX option
        ]
        dialog.setNameFilters(filters)
        dialog.setDefaultSuffix("odt")  # Default to ODT
        
        if dialog.exec():
            file_path = dialog.selectedFiles()[0]
            selected_filter = dialog.selectedNameFilter()
            
            try:
                if "OpenDocument" in selected_filter:
                    writer = QTextDocumentWriter(file_path)
                    writer.setFormat(b'odf')  # ODT format
                    if not writer.write(self.text_editor.document()):
                        raise Exception("Failed to write ODT file")
                elif "PDF" in selected_filter:
                    printer = QPrinter(QPrinter.HighResolution)
                    printer.setOutputFormat(QPrinter.PdfFormat)
                    printer.setOutputFileName(file_path)
                    self.text_editor.document().print_(printer)
                elif "Markdown" in selected_filter:
                     with open(file_path, 'w', encoding='utf-8') as file:
                        markdown_text = self.text_editor.toMarkdown(QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
                        file.write(markdown_text)
                elif "Final Draft" in selected_filter:
                    # Call new method to handle FDX export
                    self.export_to_fdx(file_path, self.text_editor.document())
                else:  # Plain text
                    with open(file_path, 'w', encoding='utf-8') as file:
                        file.write(self.text_editor.toPlainText())
                        
                self.statusBar().showMessage(f"Successfully exported to {file_path}", 3000)
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export text: {str(e)}")

    def setup_format_actions(self):
        """Connect formatting actions"""
        # Font family and size connections
        self.font_combo.currentFontChanged.connect(
            lambda font: self.format_text("font", font))
        
        self.font_size.currentTextChanged.connect(
            lambda size: self.format_text("font", QFont(self.font_combo.currentFont().family(), int(size))))
        
        # Style connections
        self.bold_action.triggered.connect(
            lambda: self.format_text("style", "bold"))
        self.italic_action.triggered.connect(
            lambda: self.format_text("style", "italic"))
        self.underline_action.triggered.connect(
            lambda: self.format_text("style", "underline"))
        
        # Alignment connections
        self.align_left.triggered.connect(
            lambda: self.format_text("alignment", Qt.AlignLeft))
        self.align_center.triggered.connect(
            lambda: self.format_text("alignment", Qt.AlignCenter))
        self.align_right.triggered.connect(
            lambda: self.format_text("alignment", Qt.AlignRight))
        self.align_justify.triggered.connect(
            lambda: self.format_text("alignment", Qt.AlignJustify))

    def setup_connections(self):
        """Setup all signal connections"""
        # Text editor signals
        self.text_editor.textChanged.connect(self.document_changed)
        self.text_editor.textChanged.connect(self.delayed_ai_update)

        # File operations
        self.new_window_btn.clicked.connect(self.open_new_window)  # Add this line
        
        # File tree actions - use single click for selection
        self.file_tree.itemClicked.connect(self.file_tree_clicked)
        self.file_tree.itemDoubleClicked.connect(self.expand_folder)
        self.file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self.show_file_context_menu)
        self.new_file_btn.clicked.connect(lambda: self.create_new_file())
        self.new_folder_btn.clicked.connect(lambda: self.create_new_folder())
        
        # Connect AI panel model changes to settings save
        self.ai_panel.server_combo.currentTextChanged.connect(lambda: self.save_window_settings())
        self.ai_panel.model_combo.currentTextChanged.connect(lambda: self.save_window_settings())
        self.ai_panel.char_combo.currentTextChanged.connect(lambda: self.save_window_settings())

    def file_tree_clicked(self, item, column):
        """Handle single-click on file tree items"""
        data = item.data(0, Qt.UserRole)
        if isinstance(data, LangoTangoDocument):
            # Store current document state before switching
            if self.current_document:
                self.current_document.content = qtextedit_to_json(self.text_editor)
                
            # Set new current document
            self.current_document = data
            
            # Block signals while loading content
            self.text_editor.blockSignals(True)
        
            # Check if content is empty - if so, explicitly set default formatting
            if not data.content:
                self.text_editor.clear()
                # Force default font settings
                cursor = self.text_editor.textCursor()
                format = QTextCharFormat()
                format.setFont(QFont("Courier New", 12))
                cursor.setCharFormat(format)
                self.text_editor.setTextCursor(cursor)
            else:
                json_to_qtextedit(data.content, self.text_editor)
            
            self.text_editor.blockSignals(False)
            
            # Enable undo/redo based on stack states
            has_undo = len(data.undo_stack) > 1
            has_redo = len(data.redo_stack) > 0
            
            self.undo_shortcut.setEnabled(has_undo)
            self.redo_shortcut.setEnabled(has_redo)
            
        elif isinstance(data, LangoTangoFolder):
            # Handle folder display as before...
            self.text_editor.blockSignals(True)
            self.text_editor.clear()
            cursor = self.text_editor.textCursor()
            
            block_format = QTextBlockFormat()
            block_format.setAlignment(Qt.AlignCenter)
            cursor.setBlockFormat(block_format)
            
            char_format = QTextCharFormat()
            char_format.setFont(QFont("Courier New", 16))
            
            cursor.insertText(data.name, char_format)
            
            self.current_document = None
            self.text_editor.blockSignals(False)
            
            # Disable undo/redo for folders
            self.undo_shortcut.setEnabled(False)
            self.redo_shortcut.setEnabled(False)

    def expand_folder(self, item, column):
        """Handle double-click to expand/collapse folders"""
        data = item.data(0, Qt.UserRole)
        if isinstance(data, LangoTangoFolder):
            # Toggle folder expansion state
            item.setExpanded(not item.isExpanded())

    def update_file_tree(self):
        """Update the file tree with the current file structure"""
        self.file_tree.clear()
        
        def add_items(parent_item, folder):
            for item in folder.items:
                if isinstance(item, LangoTangoFolder):
                    folder_item = QTreeWidgetItem(parent_item)
                    folder_item.setText(0, item.name)
                    folder_item.setIcon(0, self.folder_icon)
                    folder_item.setData(0, Qt.UserRole, item)
                    add_items(folder_item, item)
                else:  # Document
                    doc_item = QTreeWidgetItem(parent_item)
                    # Remove .lango extension for display
                    display_name = item.name
                    if display_name.endswith(".lango"):
                        display_name = display_name[:-6]
                    doc_item.setText(0, display_name)
                    doc_item.setIcon(0, self.file_icon)
                    doc_item.setData(0, Qt.UserRole, item)
        
        root_item = QTreeWidgetItem(self.file_tree)
        root_item.setText(0, self.root_folder.name)
        root_item.setIcon(0, self.folder_icon)
        root_item.setData(0, Qt.UserRole, self.root_folder)
        add_items(root_item, self.root_folder)

        # Add fixed research folder
        research_item = QTreeWidgetItem(self.file_tree)
        research_item.setText(0, self.research_folder.name)
        research_item.setIcon(0, self.research_icon)
        research_item.setData(0, Qt.UserRole, self.research_folder)
        add_items(research_item, self.research_folder)
        
        # Add fixed trash folder at the bottom
        trash_item = QTreeWidgetItem(self.file_tree)
        trash_item.setText(0, self.trash_folder.name)
        trash_item.setIcon(0, self.trash_icon)
        trash_item.setData(0, Qt.UserRole, self.trash_folder)
        add_items(trash_item, self.trash_folder)
        
        self.file_tree.expandAll()

    def show_file_context_menu(self, position):
        """Show context menu for file tree items"""
        item = self.file_tree.itemAt(position)
        if (item is None):
            return
            
        menu = QMenu()
        data = item.data(0, Qt.UserRole)
        
        if data == self.trash_folder:
            # Special menu for trash folder
            if len(self.trash_folder.items) > 0:
                empty_action = menu.addAction("Empty Trash")
                action = menu.exec(self.file_tree.mapToGlobal(position))
                if action == empty_action:
                    self.empty_trash()
            return
        
        if data == self.research_folder:
            # Special menu for research folder
            add_file_action = menu.addAction("Add File")
            add_folder_action = menu.addAction("Add Folder")
                
            action = menu.exec(self.file_tree.mapToGlobal(position))
            
            if action == add_file_action:
                self.create_new_file(parent_folder=data)
            elif action == add_folder_action:
                self.create_new_folder(parent_folder=data)
            return
            
        if isinstance(data, LangoTangoFolder) and data != self.trash_folder and data != self.research_folder:
            add_file_action = menu.addAction("Add File")
            add_folder_action = menu.addAction("Add Folder")
            rename_action = menu.addAction("Rename")
            delete_action = menu.addAction("Move to Trash")
            
            action = menu.exec(self.file_tree.mapToGlobal(position))
            
            if action == add_file_action:
                self.create_new_file(parent_folder=data)
            elif action == add_folder_action:
                self.create_new_folder(parent_folder=data)
            elif action == rename_action:
                self.rename_item(item)
            elif action == delete_action:
                self.move_to_trash(item)
                
        elif isinstance(data, LangoTangoDocument):
            rename_action = menu.addAction("Rename")
            delete_action = menu.addAction("Move to Trash")
            
            # Add a "Move to Research" option if not already in Research
            parent_item = item.parent()
            parent_data = parent_item.data(0, Qt.UserRole) if parent_item else None
            if parent_data != self.research_folder:
                research_action = menu.addAction("Move to Research")
            else:
                research_action = None
            
            action = menu.exec(self.file_tree.mapToGlobal(position))
            
            if action == rename_action:
                self.rename_item(item)
            elif action == delete_action:
                self.move_to_trash(item)
            elif research_action and action == research_action:
                self.move_to_research(item)

    def move_to_research(self, item):
        """Move an item to the research folder"""
        data = item.data(0, Qt.UserRole)
        parent_item = item.parent()
    
        if parent_item:
            parent_data = parent_item.data(0, Qt.UserRole)
            if isinstance(parent_data, LangoTangoFolder):
                parent_data.items.remove(data)
                self.research_folder.items.append(data)
                parent_data.modified = datetime.now().isoformat()
                self.update_file_tree()

    def move_to_trash(self, item):
        """Move an item to the trash folder"""
        data = item.data(0, Qt.UserRole)
        parent_item = item.parent()
        
        if parent_item and parent_item.data(0, Qt.UserRole) != self.trash_folder:
            parent_data = parent_item.data(0, Qt.UserRole)
            if isinstance(parent_data, LangoTangoFolder):
                parent_data.items.remove(data)
                self.trash_folder.items.append(data)
                parent_data.modified = datetime.now().isoformat()
                self.update_file_tree()

    def empty_trash(self):
        """Permanently delete all items in the trash"""
        reply = QMessageBox.question(
            self, 
            "Empty Trash",
            "Are you sure you want to permanently delete all items in the trash?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.trash_folder.items.clear()
            self.update_file_tree()

    def delete_item(self, item):
        """Redirect delete operations to move_to_trash"""
        self.move_to_trash(item)
    
    def create_new_file(self, parent_folder=None):
        """Create a new file in the selected folder"""
        if parent_folder is None:
            # Get selected folder or use root
            selected = self.file_tree.selectedItems()
            if selected and isinstance(selected[0].data(0, Qt.UserRole), LangoTangoFolder):
                parent_folder = selected[0].data(0, Qt.UserRole)
            else:
                parent_folder = self.root_folder
                
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            # Add .lango extension to the actual document name but don't display it
            display_name = name
            if not name.endswith(".lango"):
                name += ".lango"
                
            new_doc = LangoTangoDocument(name=name)
            parent_folder.items.append(new_doc)
            parent_folder.modified = datetime.now().isoformat()
            self.update_file_tree()
    
    def create_new_folder(self, parent_folder=None):
        """Create a new folder in the selected folder"""
        if parent_folder is None:
            # Get selected folder or use root
            selected = self.file_tree.selectedItems()
            if selected and isinstance(selected[0].data(0, Qt.UserRole), LangoTangoFolder):
                parent_folder = selected[0].data(0, Qt.UserRole)
            else:
                parent_folder = self.root_folder
                
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            new_folder = LangoTangoFolder(name=name)
            parent_folder.items.append(new_folder)
            parent_folder.modified = datetime.now().isoformat()
            self.update_file_tree()
    
    def rename_item(self, item):
        """Rename a file or folder"""
        data = item.data(0, Qt.UserRole)
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=data.name)
        if ok and name:
            # Check if this is the root folder that's being renamed
            is_root_folder = (data == self.root_folder)
            
            # Update the name and modified timestamp
            data.name = name
            data.modified = datetime.now().isoformat()
            item.setText(0, name)
            
            # If we're renaming the root folder, update the window title
            if is_root_folder and self.current_file_path:
                base_filename = os.path.basename(self.current_file_path)
                self.setWindowTitle(f"LangoTango - {name}")
                
                # Make sure to save changes immediately to avoid corruption
                self.save_document()
    
    def delayed_ai_update(self):
        """Delay AI updates to prevent recursion"""
        text = self.text_editor.toPlainText()
        QTimer.singleShot(1000, lambda: self.ai_panel.text_changed(text))
    
    def tree_drop_event(self, event):
        """Handle drop events in the file tree"""
        # Get the items involved
        dragged_item = self.file_tree.currentItem()
        target_item = self.file_tree.itemAt(event.position().toPoint())
        
        if not dragged_item or not target_item:
            event.ignore()
            return
            
        # Get the data objects
        dragged_data = dragged_item.data(0, Qt.UserRole)
        target_data = target_item.data(0, Qt.UserRole)
        
        # Don't allow dropping a folder into its own subfolder
        if isinstance(dragged_data, LangoTangoFolder):
            parent = target_item
            while parent:
                if parent == dragged_item:
                    event.ignore()
                    return
                parent = parent.parent()
        
        # Remove item from its old parent
        old_parent_item = dragged_item.parent()
        if old_parent_item:
            old_parent_data = old_parent_item.data(0, Qt.UserRole)
            if isinstance(old_parent_data, LangoTangoFolder):
                old_parent_data.items.remove(dragged_data)
        
        # Add item to new parent
        if isinstance(target_data, LangoTangoFolder):
            # Dropping onto a folder
            target_data.items.append(dragged_data)
        else:
            # Dropping next to a file/folder
            parent_item = target_item.parent()
            if parent_item:
                parent_data = parent_item.data(0, Qt.UserRole)
                if isinstance(parent_data, LangoTangoFolder):
                    # Find the position to insert
                    index = parent_item.indexOfChild(target_item)
                    parent_data.items.insert(index, dragged_data)
        
        # Update timestamps
        current_time = datetime.now().isoformat()
        dragged_data.modified = current_time
        if isinstance(target_data, LangoTangoFolder):
            target_data.modified = current_time
        
        # Let Qt handle the visual update
        event.accept()
        
        # Refresh the tree to ensure consistent state
        self.update_file_tree()
    
    def setup_status_bar(self):
        """Set up the status bar with word count and copyright info"""
        self.statusBar().setStyleSheet("QStatusBar { border-top: none; }")
        
        # Create word count label
        self.word_count_label = QLabel()
        self.statusBar().addWidget(self.word_count_label)
        
        # Create last save timestamp label
        self.last_save_label = QLabel("Not saved yet")
        self.statusBar().addWidget(self.last_save_label)
        
        # Create copyright label on the right
        copyright_label = QLabel("LangoTango version 1.0 by Shokunin Studio © 2025")
        self.statusBar().addPermanentWidget(copyright_label)
        
        # Initial word count update
        self.update_word_count()

    def count_words_in_folder(self, folder):
        """Count words in all documents by getting each document's own saved content"""
        total = 0
        # Create a temporary QTextDocument to parse HTML
        temp_doc = QTextEdit()
        
        for item in folder.items:
            if isinstance(item, LangoTangoDocument):
                if item.content:  # Use each document's saved content
                    json_to_qtextedit(item.content, temp_doc)
                    doc_text = temp_doc.toPlainText().strip()
                    total += len([w for w in doc_text.split() if w.strip()])
            elif isinstance(item, LangoTangoFolder):
                total += self.count_words_in_folder(item)
        return total

    def update_word_count(self):
        """Update word counts - no HTML, no formatting"""
        # Current document - just plain text split into words
        current_words = len([w for w in self.text_editor.toPlainText().split() if w.strip()])
        
        # Total is just sum of all document word counts 
        total_words = self.count_words_in_folder(self.root_folder)
        
        self.word_count_label.setText(f"Current Document: {current_words:,} words | Total Project: {total_words:,} words")

    def auto_save(self):
        """Auto-save the current project"""
        if self.current_file_path:
            try:
                self.save_to_file(self.current_file_path)
                current_time = datetime.now().strftime("%H:%M")
                self.last_save_label.setText(f"Last Saved at {current_time}")
            except Exception as e:
                print(f"Auto-save error: {str(e)}")  # Log error but don't show message box for auto-save

    # File operations
    def new_document(self):
        """Create a new document"""
        self.current_document = LangoTangoDocument()
        self.current_file_path = None
        self.text_editor.clear()
        self.setWindowTitle("LangoTango")
    
    def open_document(self):
        """Open a document from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Document", "", "LangoTango Files (*.lango);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as file:
                    data = json.load(file)
                    
                if not isinstance(data, dict):
                    raise ValueError("Invalid file format: not a JSON object")
                    
                if "root_folder" in data:
                    self.load_workspace(data)
                elif isinstance(data, dict) and "name" in data:  # Check for single document format
                    self.load_document(data)
                else:
                    raise ValueError("Invalid file format: missing required fields")
                    
                self.current_file_path = file_path
                self.setWindowTitle(f"LangoTango - {os.path.basename(file_path)}")
                    
            except json.JSONDecodeError as e:
                QMessageBox.critical(self, "Error", f"Failed to parse file: Invalid JSON format")
            except ValueError as e:
                QMessageBox.critical(self, "Error", str(e))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file: {str(e)}")
    
    def save_document(self):
        """Save the current document"""
        if self.current_file_path:
            self.save_to_file(self.current_file_path)
        else:
            # First time saving
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                "Save Project", 
                "Untitled.lango", 
                "LangoTango Files (*.lango);;All Files (*)"
            )
            
            if file_path:
                if not file_path.endswith('.lango'):
                    file_path += '.lango'
                
                self.save_to_file(file_path)
                self.current_file_path = file_path
                self.setWindowTitle(f"LangoTango - {os.path.basename(file_path)}")
    
    def save_document_as(self):
        """Save the document with a new name"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Document", "", "LangoTango Files (*.lango);;All Files (*)"
        )
        
        if file_path:
            if not file_path.endswith('.lango'):
                file_path += '.lango'
                
            self.save_to_file(file_path)
            self.current_file_path = file_path
            self.setWindowTitle(f"LangoTango - {os.path.basename(file_path)}")
    
    def save_to_file(self, file_path):
        """Save the current state to a file with atomic write"""
        # Create backup directory in user's home folder
        backup_dir = Path.home() / 'LangoTango Backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Create temporary file path
        temp_path = file_path + '.tmp'
        
        try:
            # Update current document
            if self.current_document:
                self.document_changed()
                current_doc_dict = self.current_document.to_dict()
            else:
                current_doc_dict = None

            # Create workspace data
            data = {
                "root_folder": self.root_folder.to_dict(),
                "research_folder": self.research_folder.to_dict(),
                "trash_folder": self.trash_folder.to_dict(),
                "current_document": current_doc_dict
            }
            
            # Write to temporary file first
            with open(temp_path, 'w') as file:
                json.dump(data, file, indent=2)
                file.flush()
                os.fsync(file.fileno())  # Ensure data is written to disk
                
            # Create backup of existing file if it exists
            if os.path.exists(file_path):
                # Create timestamped backup filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{Path(file_path).stem}_{timestamp}.bak"
                backup_path = backup_dir / backup_name
                
                try:
                    # Copy existing file to backup location
                    import shutil
                    shutil.copy2(file_path, backup_path)
                except Exception as e:
                    print(f"Warning: Failed to create backup: {str(e)}")
                    
            # Atomic rename of temporary file to final file
            os.replace(temp_path, file_path)
            
            # Update last save timestamp
            current_time = datetime.now().strftime("%H:%M")
            self.last_save_label.setText(f"Last Saved at {current_time}")
            
        except Exception as e:
            # Clean up temporary file if it exists
            if os.path.exists(temp_path):
                os.remove(temp_path)
            QMessageBox.critical(self, "Error", f"Failed to save file: {str(e)}")
            raise

    def load_workspace(self, data):
        """Load a workspace from data"""
        # Check that root_folder exists in the data
        if "root_folder" not in data:
            raise ValueError("Invalid file format: missing root folder")
            
        folder_data = data["root_folder"]
        self.root_folder = LangoTangoFolder.from_dict(folder_data)
        
        if "research_folder" in data:
            research_data = data["research_folder"]
            self.research_folder = LangoTangoFolder.from_dict(research_data)
        else:
            # Create empty research folder if not in saved data (for backwards compatibility)
            self.research_folder = LangoTangoFolder("Research")
        
        if "trash_folder" in data:
            trash_data = data["trash_folder"]
            self.trash_folder = LangoTangoFolder.from_dict(trash_data)
        else:
            # Create empty trash folder if not in saved data
            self.trash_folder = LangoTangoFolder("Trash")
        
        if "current_document" in data and data["current_document"] is not None:
            self.current_document = LangoTangoDocument.from_dict(data["current_document"])
            json_to_qtextedit(self.current_document.content, self.text_editor)
        else:
            self.current_document = None
            self.text_editor.clear()
            
        self.update_file_tree()

        # Select first document after loading 
        self.select_first_document()
    
    def load_document(self, data):
        """Load a single document from data"""
        self.current_document = LangoTangoDocument.from_dict(data)
        json_to_qtextedit(self.current_document.content, self.text_editor)

    def compile_project(self):
        """Show compile options and compile the project"""
        dialog = CompileOptionsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # The saving is now handled completely within the CompileOptionsDialog.accept() method
            # No need to duplicate the save code here
            pass

    def get_compiled_content(self, with_formatting=False):
        content = []
        def process_folder(folder, level=0):
            if folder == self.research_folder or folder == self.trash_folder:
                return
            for item in folder.items:
                if isinstance(item, LangoTangoDocument):
                    if with_formatting:
                        title = item.name[:-7] if item.name.endswith(".lango") else item.name
                        header = f'<div style="font-family: Courier New; font-size: 14pt; text-align: center;">{title}</div><br/>'
                        content.append(header)
                        # Convert JSON content to HTML using QTextEdit
                        temp_edit = QTextEdit()
                        json_to_qtextedit(item.content, temp_edit)
                        content.append(temp_edit.toHtml())
                        content.append("<br/><br/>")
                    else:
                        title = item.name[:-7] if item.name.endswith(".lango") else item.name
                        header = f"\n{'#' * (level + 2)} {title}\n\n"
                        content.append(header)
                        # Convert JSON content to plain text
                        temp_edit = QTextEdit()
                        json_to_qtextedit(item.content, temp_edit)
                        content.append(temp_edit.toPlainText())
                        content.append("\n\n")
                elif isinstance(item, LangoTangoFolder):
                    if with_formatting:
                        header = f'<div style="font-family: Courier New; font-size: 16pt; text-align: center;">{item.name}</div><br/>'
                        content.append(header)
                    else:
                        header = f"\n{'#' * (level + 1)} {item.name}\n\n"
                        content.append(header)
                    process_folder(item, level + 1)
        if with_formatting:
            content.append(f'<div style="font-family: Courier New; font-size: 18pt; text-align: center;">{self.root_folder.name}</div><br/>')
        else:
            content.append(f"# {self.root_folder.name}\n\n")
        process_folder(self.root_folder)
        return "".join(content) if with_formatting else "".join(content)

    # Add to LangoTangoWordProcessor class after compile_project method
    def search_project(self, query):
        """Search through all documents in the project"""
        results = []
        
        def get_excerpt(text, query, context_length=40):
            """Get excerpt of text around the query word"""
            idx = text.lower().find(query.lower())
            if idx == -1:
                return ""
            
            # Get start and end indices for the excerpt
            start = max(0, idx - context_length)
            end = min(len(text), idx + len(query) + context_length)
            
            # Add ellipsis if needed
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            
            return prefix + text[start:end].strip() + suffix

        def search_folder(folder):
            for item in folder.items:
                if isinstance(item, LangoTangoDocument):
                    # Create temporary QTextEdit to get plain text
                    temp_edit = QTextEdit()
                    json_to_qtextedit(item.content, temp_edit)
                    plain_text = temp_edit.toPlainText()
                    
                    # Search in content
                    if query.lower() in plain_text.lower():
                        excerpt = get_excerpt(plain_text, query)
                        results.append({
                            'name': excerpt,  # Only show the excerpt
                            'icon': self.file_icon,
                            'data': item
                        })
                elif isinstance(item, LangoTangoFolder):
                    search_folder(item)  # Just search inside folders, don't show folder names
        
        search_folder(self.root_folder)
        return results

    def navigate_to_item(self, item):
        """Navigate to a search result"""
        if isinstance(item, LangoTangoDocument):
            def find_item_in_tree(root_item, target):
                for i in range(root_item.childCount()):
                    child = root_item.child(i)
                    data = child.data(0, Qt.UserRole)
                    if data == target:
                        self.file_tree.setCurrentItem(child)
                        return True
                    if child.childCount() > 0:
                        if find_item_in_tree(child, target):
                            return True
                return False
            
            root_item = self.file_tree.topLevelItem(0)
            find_item_in_tree(root_item, item)
            
            # Load the document
            self.current_document = item
            json_to_qtextedit(item.content, self.text_editor)
        elif isinstance(item, LangoTangoFolder):
            def find_folder_in_tree(root_item, target):
                for i in range(root_item.childCount()):
                    child = root_item.child(i)
                    data = child.data(0, Qt.UserRole)
                    if data == target:
                        self.file_tree.setCurrentItem(child)
                        child.setExpanded(True)
                        return True
                    if child.childCount() > 0:
                        if find_folder_in_tree(child, target):
                            return True
                return False
                
            root_item = self.file_tree.topLevelItem(0)
            find_folder_in_tree(root_item, item)

    def open_find_replace_dialog(self):
        """Open the Find/Replace dialog"""
        dialog = FindReplaceDialog(self)
        dialog.exec()

    def undo_document(self):
        """Undo the current document's last change"""
        if self.current_document:
            content = self.current_document.undo()
            if content != qtextedit_to_json(self.text_editor):
                # Block signals to prevent recursive state addition
                self.text_editor.blockSignals(True)
                json_to_qtextedit(content, self.text_editor)
                self.text_editor.blockSignals(False)
                
                # Update undo/redo availability
                self.undo_shortcut.setEnabled(len(self.current_document.undo_stack) > 1)
                self.redo_shortcut.setEnabled(len(self.current_document.redo_stack) > 0)

    def redo_document(self):
        """Redo the current document's last undone change"""
        if self.current_document:
            content = self.current_document.redo()
            if content != qtextedit_to_json(self.text_editor):
                # Block signals to prevent recursive state addition
                self.text_editor.blockSignals(True)
                json_to_qtextedit(content, self.text_editor)
                self.text_editor.blockSignals(False)
                
                # Update undo/redo availability
                self.undo_shortcut.setEnabled(len(self.current_document.undo_stack) > 1)
                self.redo_shortcut.setEnabled(len(self.current_document.redo_stack) > 0)

    def open_query_dialog(self):
        """Open the Query dialog for the current document"""
        if not self.current_document:
            QMessageBox.warning(self, "No Document", "Please select a document to query.")
            return

        dialog = QueryDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # Update the editor content with the processed content from the dialog
            new_content = dialog.processed_content
            # Block signals to prevent immediate re-triggering of document_changed
            self.text_editor.blockSignals(True)
            json_to_qtextedit(new_content, self.text_editor)
            self.text_editor.blockSignals(False)
            # Manually trigger document_changed to save state after update
            self.document_changed()
            self.statusBar().showMessage("Document updated with query results.", 3000)
        
    def open_new_window(self):
        """Open a new application window"""
        new_window = LangoTangoWordProcessor()
        new_window.initialize_project()
        new_window.show()
        # Store reference to prevent garbage collection
        if not hasattr(self, '_additional_windows'):
            self._additional_windows = []
        self._additional_windows.append(new_window)

    def export_to_fdx(self, file_path, document):
        """Export document to Final Draft XML format (.fdx)"""
        # Import XML library
        import xml.etree.ElementTree as ET
        
        try:
            # Parse the document to identify screenplay elements
            script_elements = self.parse_screenplay_elements(document)
            
            # Create FDX structure
            fdx_root = ET.Element("FinalDraft", {
                "DocumentType": "Script",
                "Template": "No",
                "Version": "1"
            })
            content = ET.SubElement(fdx_root, "Content")
            
            # Add screenplay elements
            for element in script_elements:
                para = ET.SubElement(content, "Paragraph", {"Type": element["type"]})
                text = ET.SubElement(para, "Text")
                text.text = element["text"]
            
            tree = ET.ElementTree(fdx_root)
            
            # Save file with proper headers
            with open(file_path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n')
                f.write('<!DOCTYPE FinalDraft PUBLIC "-//Final Draft//DTD Final Draft 1.0//EN" "FinalDraft.dtd">\n')
                tree.write(f, encoding="unicode")
                
        except Exception as e:
            raise Exception(f"Failed to create FDX file: {str(e)}")

    def parse_screenplay_elements(self, document):
        """Parse a QTextDocument to identify screenplay elements based on formatting"""
        script_elements = []
        
        # Process each block (paragraph)
        for i in range(document.blockCount()):
            block = document.findBlockByNumber(i)
            text = block.text().strip()
            
            if not text:  # Skip empty blocks
                continue
                
            # Determine element type based on alignment and text formatting
            alignment = block.blockFormat().alignment()
            
            if alignment == Qt.AlignLeft:
                # Detect if scene heading (all caps, possibly starting with INT/EXT)
                if text.isupper() or text.startswith(("INT.", "EXT.", "INT ", "EXT ")):
                    element_type = "Scene Heading"
                else:
                    element_type = "Action"
                    
            elif alignment == Qt.AlignCenter:
                # Detect if character name (all caps)
                if text.isupper():
                    element_type = "Character"
                # Check if it's a parenthetical (starts and ends with parentheses)
                elif text.startswith("(") and text.endswith(")"):
                    element_type = "Parenthetical"
                else:
                    element_type = "Dialogue"
                    
            elif alignment == Qt.AlignRight:
                element_type = "Transition"
            
            else:
                # Default to Action for any other alignment
                element_type = "Action"
            
            script_elements.append({"type": element_type, "text": text})
        
        return script_elements

# Add Splash Screen class
class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(500, 500)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        
        # Create layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        # Create label and set image
        label = QLabel(self)
        
        # Get absolute path to the splash image
        splash_path = get_splash_image_path()
        pixmap = QPixmap(splash_path)
        
        if pixmap.isNull():
            error_msg = f"Failed to load splash image from: {splash_path}"
            print(error_msg)  # Debug output
            label.setText(error_msg)
        else:
            scaled_pixmap = pixmap.scaled(500, 500, 
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(scaled_pixmap)
        
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        
        self.center()
        
    def center(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

def get_splash_image_path():
    """Get correct path for splash image in both dev and binary"""
    if getattr(sys, 'frozen', False):
        # Running in PyInstaller bundle
        return os.path.join(sys._MEIPASS, "langotango_splash.png")
    else:
        # Running in normal Python
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "langotango_splash.png")

class SearchResultsDropdown(QWidget):
    """Custom dropdown widget for search results"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setMaximumHeight(300)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        
        self.results_list = QTreeWidget()
        self.results_list.setHeaderHidden(True)
        self.results_list.setRootIsDecorated(False)
        self.results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_list.setFocusPolicy(Qt.NoFocus)  # Prevent focus
        self.results_list.setAttribute(Qt.WA_MacShowFocusRect, False)  # Remove focus ring on macOS
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # Show without stealing focus
        self.setFocusPolicy(Qt.NoFocus)  # Prevent focus on the dropdown itself
        
        self.results_list.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #ccc;
                border-radius: 3px;
                background-color: white;
                color: black;  /* Force black text */
            }
            QTreeWidget::item {
                padding: 4px;
                color: black;  /* Force black text for items */
            }
            QTreeWidget::item:selected {
                background-color: #e0e0e0;
                color: black;  /* Keep text black when selected */
            }
        """)
        
        layout.addWidget(self.results_list)

class ProjectSearchField(QLineEdit):
    """Custom search field with dropdown results"""
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setPlaceholderText("Search project...")
        self.setFixedWidth(350)
        self.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ccc;
                border-radius: 15px;
                padding: 5px 10px;
                background-color: #f0f0f0;
                color: black;  /* Force black text */
            }
            QLineEdit:focus {
                background-color: white;
                color: black;  /* Keep text black when focused */
                border-color: #999;
            }
            QLineEdit::placeholder {
                color: #666;  /* Darker placeholder text for better visibility */
            }
        """)
        
        # Create and configure the dropdown
        self.dropdown = SearchResultsDropdown(self)
        self.dropdown.results_list.itemClicked.connect(self.on_result_clicked)
        
        # Connect return/enter key press
        self.returnPressed.connect(self.perform_search)
        
    def perform_search(self):
        """Execute the search when Return is pressed"""
        text = self.text().lower()
        if not text or not self.main_window:
            self.dropdown.hide()
            return
            
        # Get results from main window
        results = self.main_window.search_project(text)
        
        # Update dropdown
        self.dropdown.results_list.clear()
        
        if not results:
            # Show "no results" message
            item = QTreeWidgetItem(self.dropdown.results_list)
            item.setText(0, "No results found")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)  # Make item non-selectable
        else:
            # Show results
            for result in results:
                item = QTreeWidgetItem(self.dropdown.results_list)
                item.setText(0, result['name'])
                item.setIcon(0, result['icon'])
                item.setData(0, Qt.UserRole, result['data'])
        
        # Position and show dropdown
        pos = self.mapToGlobal(self.rect().bottomLeft())
        self.dropdown.move(pos.x(), pos.y() + 2)
        self.dropdown.setFixedWidth(400)  # Changed from self.width() to match search field
        self.dropdown.show()
            
    def on_result_clicked(self, item):
        """Handle result selection"""
        if self.main_window and item.flags() & Qt.ItemIsEnabled:
            data = item.data(0, Qt.UserRole)
            self.main_window.navigate_to_item(data)
            self.dropdown.hide()
            self.clear()

# Add this class after the SearchResultsDropdown class
class CompileOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compile Options")
        self.setFixedSize(1000, 1000)  # Increased dialog height
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowMaximizeButtonHint)  # Remove maximize button
        self.processed_content = ""
        self.original_content = ""
        self.setup_ui()
        self.fetch_models()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Create top controls section using QFormLayout
        controls_layout = QFormLayout()
        controls_layout.setSpacing(10)

        # LLM Server selection (no font selection above this)
        self.server_combo = QComboBox()
        self.server_combo.addItems(["Ollama", "LM Studio"])
        self.server_combo.currentTextChanged.connect(self.fetch_models)
        controls_layout.addRow("LLM Server:", self.server_combo)

        # Model selection
        self.model_combo = QComboBox()
        controls_layout.addRow("Model:", self.model_combo)

        # Add controls to main layout
        layout.addLayout(controls_layout)

        # Instructions for the AI
        layout.addWidget(QLabel("Instructions for the AI (optional):"))
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("")  # Empty placeholder text
        self.prompt_input.setMaximumHeight(125) # Keep prompt input height the same
        self.prompt_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)  # Adjust vertical policy
        layout.addWidget(self.prompt_input)

        # Preview section with splitter
        preview_splitter = QSplitter(Qt.Horizontal)
        
        # Document preview
        doc_preview_group = QWidget()
        doc_preview_layout = QVBoxLayout(doc_preview_group)
        doc_preview_layout.addWidget(QLabel("Compiled Project Preview:"))
        self.doc_preview = QTextEdit()
        self.doc_preview.setReadOnly(True)
        doc_preview_layout.addWidget(self.doc_preview)
        preview_splitter.addWidget(doc_preview_group)
        doc_preview_group.setMinimumHeight(600)
        doc_preview_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # AI preview
        ai_preview_group = QWidget()
        ai_preview_layout = QVBoxLayout(ai_preview_group)
        ai_preview_layout.addWidget(QLabel("AI Processing Preview:"))
        self.ai_preview = QTextEdit()
        self.ai_preview.setReadOnly(True)
        self.ai_preview.setPlaceholderText("AI processed content will appear here...")
        ai_preview_layout.addWidget(self.ai_preview)
        preview_splitter.addWidget(ai_preview_group)
        ai_preview_group.setMinimumHeight(600)
        ai_preview_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Set equal sizes for splitter
        preview_splitter.setSizes([600, 600])
        layout.addWidget(preview_splitter)

        # Process button
        self.process_btn = QPushButton("Process with AI")
        self.process_btn.clicked.connect(self.process_content)
        layout.addWidget(self.process_btn)

        # Add warning label
        warning_label = QLabel("It is not recommended to process long projects with AI unless you have a lot of VRAM. Use Query on single documents instead.")
        warning_label.setStyleSheet("color: #333; font-size: 12px;")
        warning_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(warning_label)

        # Progress indicator
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: gray;")
        layout.addWidget(self.progress_label)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Load initial compiled project content with formatting
        parent = self.parent()
        if parent:
            compiled_doc = QTextDocument()
            compiled_doc.setDefaultFont(QFont("Courier New", 12))
            content = parent.get_compiled_content(with_formatting=True)
            compiled_doc.setHtml(content)
            self.doc_preview.setDocument(compiled_doc)
            self.original_content = compiled_doc.toHtml()

    def process_content(self):
        """Process content with AI if instructions are provided"""
        if hasattr(self, 'worker') and self.worker.isRunning():
            # Cancel ongoing processing
            self.worker.stop()
            self.process_btn.setText("Process with AI")
            self.progress_label.setText("Processing cancelled")
            return
            
        if not self.prompt_input.toPlainText().strip():
            self.ai_preview.clear()
            self.processed_content = self.original_content
            self.progress_label.setText("No AI processing requested")
            return
            
        self.progress_label.setText("Processing with AI...")
        self.process_btn.setText("Cancel")
        QApplication.processEvents()
        
        # Create temp document to get plain text for AI
        temp_doc = QTextDocument()
        temp_doc.setHtml(self.original_content)
        
        # Initialize result document with formatting
        self.result_doc = QTextDocument()
        self.result_doc.setDefaultFont(QFont("Courier New", 12))
        
        # Set up cursor with left alignment
        self.result_cursor = QTextCursor(self.result_doc)
        block_format = QTextBlockFormat()
        block_format.setAlignment(Qt.AlignLeft)
        self.result_cursor.setBlockFormat(block_format)
        
        # Create and start worker
        self.worker = StreamingAIWorker(
            self.server_combo.currentText(),
            self.model_combo.currentText(),
            temp_doc.toPlainText(),
            self.prompt_input.toPlainText()
        )
        
        self.worker.progress.connect(self.handle_progress)
        self.worker.finished.connect(self.handle_finished)
        self.worker.error.connect(self.handle_error)
        
        self.worker.start()

    def handle_progress(self, text):
        """Handle streaming text updates"""
        self.result_cursor.insertText(text)
        self.ai_preview.setDocument(self.result_doc)
        # Scroll to bottom
        scrollbar = self.ai_preview.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def handle_finished(self):
        """Handle completion of AI processing"""
        self.processed_content = self.result_doc.toHtml()
        self.progress_label.setText("AI processing complete")
        self.process_btn.setText("Process with AI")

    def handle_error(self, error_msg):
        """Handle AI processing errors"""
        self.progress_label.setText(f"Error: {error_msg}")
        self.ai_preview.setText("Error processing content")
        self.processed_content = self.original_content
        self.process_btn.setText("Process with AI")

    def accept(self):
        """Override accept to ensure content is prepared"""
        if not hasattr(self, 'processed_content') or not self.processed_content:
            # If no processing occurred or failed, use original content
            self.processed_content = self.original_content
        # Use default Courier New font
        self.selected_font = QFont("Courier New", 12)
        
        # Get the content to export
        compiled_doc = QTextDocument()
        compiled_doc.setDefaultFont(self.selected_font)
        
        if not self.prompt_input.toPlainText().strip():
            # If no AI processing, use original content with formatting
            compiled_doc.setHtml(self.original_content)
        else:
            # Use AI processed content with formatting
            compiled_doc.setHtml(self.processed_content)
        
        # Save the compiled document
        filters = "OpenDocument Text (*.odt);;PDF Document (*.pdf);;Markdown (*.md);;Plain Text (*.txt);;Final Draft (*.fdx)"
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Compiled Document",
            f"{self.parent().root_folder.name}",  # Default name without extension
            filters
        )
        
        if not file_path:
            return  # User canceled
            
        try:
            # Determine format based on selected filter or file extension
            if "(*.odt)" in selected_filter or file_path.endswith(".odt"):
                if not file_path.endswith('.odt'): file_path += '.odt'
                writer = QTextDocumentWriter(file_path)
                writer.setFormat(b'odf')
                if not writer.write(compiled_doc):
                    raise Exception("Failed to write ODT file")
            elif "(*.pdf)" in selected_filter or file_path.endswith(".pdf"):
                if not file_path.endswith('.pdf'): file_path += '.pdf'
                printer = QPrinter(QPrinter.HighResolution)
                printer.setOutputFormat(QPrinter.PdfFormat)
                printer.setOutputFileName(file_path)
                compiled_doc.print_(printer)
            elif "(*.md)" in selected_filter or file_path.endswith(".md"):
                if not file_path.endswith('.md'): file_path += '.md'
                with open(file_path, 'w', encoding='utf-8') as file:
                    markdown_text = compiled_doc.toMarkdown(QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
                    file.write(markdown_text)
            elif "(*.fdx)" in selected_filter or file_path.endswith(".fdx"):
                if not file_path.endswith('.fdx'): file_path += '.fdx'
                self.parent().export_to_fdx(file_path, compiled_doc)
            elif "(*.txt)" in selected_filter or file_path.endswith(".txt"):
                if not file_path.endswith('.txt'): file_path += '.txt'
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(compiled_doc.toPlainText())
            else:
                # Default to ODT if filter/extension is unclear
                if not file_path.endswith('.odt'): file_path += '.odt'
                writer = QTextDocumentWriter(file_path)
                writer.setFormat(b'odf')
                if not writer.write(compiled_doc):
                    raise Exception("Failed to write ODT file")
                    
            self.parent().statusBar().showMessage(
                f"Document successfully exported to {file_path}", 3000)
                
            super().accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export document: {str(e)}")

    def update_preview_font(self, font):
        """Update preview font when changed"""
        self.doc_preview.setFont(font)
        self.ai_preview.setFont(font)

    # Add this method to the CompileOptionsDialog class
    def fetch_models(self):
        """Fetch available models from the selected LLM server"""
        server = self.server_combo.currentText()
        self.model_combo.clear()
        
        try:
            if server == "Ollama":
                response = requests.get("http://localhost:11434/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [model["name"] for model in models]
                    self.model_combo.addItems(model_names)
                    self.progress_label.setText("Connected to Ollama")
                else:
                    self.progress_label.setText("Failed to connect to Ollama server")
            
            elif server == "LM Studio":
                response = requests.get("http://localhost:1234/v1/models")
                if response.status_code == 200:
                    models = response.json().get("data", [])
                    model_names = [model["id"] for model in models]
                    self.model_combo.addItems(model_names)
                    self.progress_label.setText("Connected to LM Studio")
                else:
                    self.progress_label.setText("Failed to connect to LM Studio server")
        
        except requests.exceptions.RequestException:
            self.progress_label.setText(f"Failed to connect to {server}")

# Add this new class after FindReplaceDialog
class QueryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Query Current Document")
        self.setFixedSize(1000, 1000) # Same size as CompileOptionsDialog
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowMaximizeButtonHint)
        self.processed_content = ""
        self.original_content = ""
        self.text_editor = parent.text_editor if parent else None # Store reference to editor
        self.setup_ui()
        self.fetch_models()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Create top controls section using QFormLayout (same as CompileOptionsDialog)
        controls_layout = QFormLayout()
        controls_layout.setSpacing(10)

        # LLM Server selection
        self.server_combo = QComboBox()
        self.server_combo.addItems(["Ollama", "LM Studio"])
        self.server_combo.currentTextChanged.connect(self.fetch_models)
        controls_layout.addRow("LLM Server:", self.server_combo)

        # Model selection
        self.model_combo = QComboBox()
        controls_layout.addRow("Model:", self.model_combo)

        layout.addLayout(controls_layout)

        # Instructions for the AI
        layout.addWidget(QLabel("Instructions for the AI:"))
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("Enter instructions for processing the current document...")
        self.prompt_input.setMaximumHeight(125)
        self.prompt_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addWidget(self.prompt_input)

        # Preview section with splitter (same as CompileOptionsDialog)
        preview_splitter = QSplitter(Qt.Horizontal)

        # Document preview (shows current document)
        doc_preview_group = QWidget()
        doc_preview_layout = QVBoxLayout(doc_preview_group)
        doc_preview_layout.addWidget(QLabel("Current Document Preview:"))
        self.doc_preview = QTextEdit()
        self.doc_preview.setReadOnly(True)
        doc_preview_layout.addWidget(self.doc_preview)
        preview_splitter.addWidget(doc_preview_group)
        doc_preview_group.setMinimumHeight(600)
        doc_preview_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # AI preview
        ai_preview_group = QWidget()
        ai_preview_layout = QVBoxLayout(ai_preview_group)
        ai_preview_layout.addWidget(QLabel("AI Processing Preview:"))
        self.ai_preview = QTextEdit()
        self.ai_preview.setReadOnly(True)
        self.ai_preview.setPlaceholderText("AI processed content will appear here...")
        ai_preview_layout.addWidget(self.ai_preview)
        preview_splitter.addWidget(ai_preview_group)
        ai_preview_group.setMinimumHeight(600)
        ai_preview_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        preview_splitter.setSizes([600, 600])
        layout.addWidget(preview_splitter)

        # Process button
        self.process_btn = QPushButton("Process with AI")
        self.process_btn.clicked.connect(self.process_content)
        layout.addWidget(self.process_btn)

        # Progress indicator
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: gray;")
        layout.addWidget(self.progress_label)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Load initial current document content
        parent = self.parent()
        if parent and self.text_editor:
            # Get content directly from the editor
            self.original_content = qtextedit_to_json(self.text_editor)
            json_to_qtextedit(self.original_content, self.doc_preview)
            # Set default processed content to original until processed
            self.processed_content = self.original_content

    def process_content(self):
        """Process current document content with AI"""
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.process_btn.setText("Process with AI")
            self.progress_label.setText("Processing cancelled")
            return

        if not self.prompt_input.toPlainText().strip():
            json_to_qtextedit(self.original_content, self.ai_preview) # Show original if no prompt
            self.processed_content = self.original_content
            self.progress_label.setText("No AI processing requested")
            return

        self.progress_label.setText("Processing with AI...")
        self.process_btn.setText("Cancel")
        QApplication.processEvents()

        # Use a temporary QTextEdit to convert JSON to plain text for AI
        temp_edit = QTextEdit()
        json_to_qtextedit(self.original_content, temp_edit)
        plain_text = temp_edit.toPlainText()

        # Initialize result document with formatting
        self.result_doc = QTextDocument()
        default_font = self.text_editor.document().defaultFont() if self.text_editor else QFont("Courier New", 12)
        self.result_doc.setDefaultFont(default_font)

        self.result_cursor = QTextCursor(self.result_doc)
        block_format = QTextBlockFormat()
        block_format.setAlignment(Qt.AlignLeft) # Default alignment
        self.result_cursor.setBlockFormat(block_format)

        self.worker = StreamingAIWorker(
            self.server_combo.currentText(),
            self.model_combo.currentText(),
            plain_text, # Use plain text of current doc
            self.prompt_input.toPlainText()
        )

        self.worker.progress.connect(self.handle_progress)
        self.worker.finished.connect(self.handle_finished)
        self.worker.error.connect(self.handle_error)

        self.worker.start()

    def handle_progress(self, text):
        """Handle streaming text updates"""
        self.result_cursor.insertText(text)
        self.ai_preview.setDocument(self.result_doc)
        scrollbar = self.ai_preview.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def handle_finished(self):
        """Handle completion of AI processing"""
        # Convert self.result_doc (QTextDocument) to JSON using a temporary QTextEdit
        temp_edit = QTextEdit()
        temp_edit.setDocument(self.result_doc)
        self.processed_content = qtextedit_to_json(temp_edit)
        self.progress_label.setText("AI processing complete")
        self.process_btn.setText("Process with AI")

    def handle_error(self, error_msg):
        """Handle AI processing errors"""
        self.progress_label.setText(f"Error: {error_msg}")
        self.ai_preview.setText(f"Error processing content: {error_msg}")
        self.processed_content = self.original_content # Revert on error
        self.process_btn.setText("Process with AI")

    def accept(self):
        """Override accept to update the main editor"""
        # The processed_content is already set by handle_finished or init
        super().accept()

    def fetch_models(self):
        """Fetch available models (same as CompileOptionsDialog)"""
        server = self.server_combo.currentText()
        self.model_combo.clear()

        try:
            if server == "Ollama":
                response = requests.get("http://localhost:11434/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_names = [model["name"] for model in models]
                    self.model_combo.addItems(model_names)
                    self.progress_label.setText("Connected to Ollama")
                else:
                    self.progress_label.setText("Failed to connect to Ollama server")

            elif server == "LM Studio":
                response = requests.get("http://localhost:1234/v1/models")
                if response.status_code == 200:
                    models = response.json().get("data", [])
                    model_names = [model["id"] for model in models]
                    self.model_combo.addItems(model_names)
                    self.progress_label.setText("Connected to LM Studio")
                else:
                    self.progress_label.setText("Failed to connect to LM Studio server")

        except requests.exceptions.RequestException:
            self.progress_label.setText(f"Failed to connect to {server}")

# Add this class after the CompileOptionsDialog class
class FindReplaceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find and Replace")
        self.setMinimumWidth(500)
        
        # Initialize class variables
        self.text_editor = parent.text_editor if parent else None
        
        # Create layout with more spacing
        layout = QVBoxLayout(self)
        layout.setSpacing(10)  # Add spacing between elements
        layout.setContentsMargins(20, 20, 20, 20)  # Add margins around the dialog
        
        # Add form layout for inputs with wider spacing
        form_layout = QFormLayout()
        form_layout.setSpacing(10)  # Spacing between form rows
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)  # Allow fields to grow
        
        # Create and configure input fields
        self.find_input = QLineEdit()
        self.replace_input = QLineEdit()
        
        # Set minimum width for input fields
        self.find_input.setMinimumWidth(300)
        self.replace_input.setMinimumWidth(300)
        
        # Add styled input fields to form
        form_layout.addRow("Find:", self.find_input)
        form_layout.addRow("Replace:", self.replace_input)
        layout.addLayout(form_layout)
        
        # Add button layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)  # Add spacing between buttons
        self.find_btn = QPushButton("Find")
        self.replace_btn = QPushButton("Replace")
        self.replace_all_btn = QPushButton("Replace All")
        btn_layout.addWidget(self.find_btn)
        btn_layout.addWidget(self.replace_btn)
        btn_layout.addWidget(self.replace_all_btn)
        layout.addLayout(btn_layout)
        
        # Add status label
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        
        # Connect signals
        self.find_btn.clicked.connect(self.find_next)
        self.replace_btn.clicked.connect(self.replace_one)
        self.replace_all_btn.clicked.connect(self.replace_all)
        
        # Enable buttons based on find input
        self.find_input.textChanged.connect(self.update_button_states)
        self.update_button_states()

    def update_button_states(self):
        """Enable/disable buttons based on whether there's text to find"""
        has_find_text = bool(self.find_input.text())
        self.find_btn.setEnabled(has_find_text)
        self.replace_btn.setEnabled(has_find_text)
        self.replace_all_btn.setEnabled(has_find_text)

    def find_next(self):
        """Find the next occurrence of the search term"""
        if not self.text_editor:
            return
            
        text = self.find_input.text()
        if not text:
            return
            
        doc = self.text_editor.document()
        cursor = self.text_editor.textCursor()
        pos = cursor.position()
        
        # Try to find from current position
        found = doc.find(text, pos)
        if found.isNull():
            # Wrap around to start
            found = doc.find(text, 0)
            
        if not found.isNull():
            # Match found - select it
            self.text_editor.setTextCursor(found)
            self.status_label.setText("")
        else:
            self.status_label.setText("Text not found")

    def replace_one(self):
        """Replace the currently selected occurrence"""
        if not self.text_editor:
            return
            
        cursor = self.text_editor.textCursor()
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        
        if cursor.hasSelection() and cursor.selectedText() == find_text:
            cursor.beginEditBlock()
            cursor.insertText(replace_text)
            cursor.endEditBlock()
            self.text_editor.setTextCursor(cursor)
            self.find_next()
        else:
            self.find_next()

    def replace_all(self):
        """Replace all occurrences while preserving formatting"""
        if not self.text_editor:
            return
        
        find_text = self.find_input.text()
        replace_text = self.replace_input.text()
        if not find_text:
            return
        
        cursor = self.text_editor.textCursor()
        cursor.beginEditBlock()
        
        doc = self.text_editor.document()
        pos = 0
        count = 0
        
        while True:
            found = doc.find(find_text, pos)
            if found.isNull():
                break
            
            found.insertText(replace_text)
            pos = found.position()
            count += 1
            
        cursor.endEditBlock()
        
        if count > 0:
            self.status_label.setText(f"Replaced {count} occurrence(s)")
        else:
            self.status_label.setText("No matches found")

# Add helper functions to convert between JSON block structure and QTextEdit/QTextDocument content.
def json_to_qtextedit(json_blocks, text_edit):
    """Load JSON block structure with inline formatting into QTextEdit."""
    text_edit.clear()
    cursor = text_edit.textCursor()
    for i, block in enumerate(json_blocks):
        alignment_val = block.get('alignment', Qt.AlignLeft)
        block_fmt = QTextBlockFormat()
        block_fmt.setAlignment(Qt.AlignmentFlag(alignment_val))
        if i > 0:
            cursor.insertBlock(block_fmt)
        else:
            cursor.setBlockFormat(block_fmt)
        for span in block.get('spans', []):
            fmt = QTextCharFormat()
            font = QFont(span.get('font_family', 'Courier New'), span.get('font_size', 12))
            fmt.setFont(font)
            fmt.setFontWeight(QFont.Bold if span.get('bold') else QFont.Normal)
            fmt.setFontItalic(span.get('italic', False))
            fmt.setFontUnderline(span.get('underline', False))
            if span.get('highlight'):
                fmt.setBackground(QColor(175, 180, 65))
            # Only set foreground if color is present and not black (system default)
            if 'color' in span and span['color'] and span['color'] != '#000000':
                fmt.setForeground(QColor(span['color']))
            cursor.setCharFormat(fmt)
            cursor.insertText(span.get('text', ''))
    text_edit.moveCursor(QTextCursor.Start)

def qtextedit_to_json(text_edit):
    """Convert QTextEdit content to JSON block structure with inline formatting."""
    doc = text_edit.document()
    blocks = []
    block = doc.firstBlock()
    while block.isValid():
        block_fmt = block.blockFormat()
        alignment = int(block_fmt.alignment())
        # Extract spans (runs) with formatting
        spans = []
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                char_fmt = frag.charFormat()
                font = char_fmt.font()
                span = {
                    'text': frag.text(),
                    'font_family': font.family(),
                    'font_size': font.pointSize(),
                    'bold': font.bold(),
                    'italic': font.italic(),
                    'underline': font.underline(),
                    'highlight': char_fmt.background().color().rgb() == QColor(175, 180, 65).rgb(),
                    'color': char_fmt.foreground().color().name()
                }
                spans.append(span)
            it += 1
        blocks.append({
            'alignment': alignment,
            'spans': spans
        })
        block = block.next()
    return blocks

# Add these classes after the FindReplaceDialog class and before the json helper functions
class SpellCheckHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.spell = SpellChecker()

        self.error_format = QTextCharFormat()
        self.error_format.setUnderlineColor(QColor("red"))
        self.error_format.setUnderlineStyle(QTextCharFormat.WaveUnderline)

        self.misspelled_words = set()

    def highlightBlock(self, text):
        # Skip spell checking for special blocks (e.g. code blocks)
        if self.currentBlock().blockFormat().property(0) == "code":
            return

        word_matches = list(re.finditer(r"\b[\w']+\b", text))
        words = [match.group() for match in word_matches]
        self.misspelled_words = self.spell.unknown(words)

        for match in word_matches:
            word = match.group()
            if word in self.misspelled_words:
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, self.error_format)

class SpellCheckTextEdit(QTextEdit):
    def __init__(self, spell_checker, parent=None):
        super().__init__(parent)
        self.spell_checker = spell_checker

    def contextMenuEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        cursor.select(QTextCursor.WordUnderCursor)
        selected_word = cursor.selectedText()

        menu = QMenu(self)

        if selected_word in self.spell_checker.highlighter.spell.unknown([selected_word]):
            suggestions = list(self.spell_checker.highlighter.spell.candidates(selected_word))
            suggestions = sorted(suggestions)[:5] or ["(No suggestions)"]

            for suggestion in suggestions:
                action = QAction(suggestion, self)
                action.triggered.connect(lambda _, s=suggestion: self.replaceWord(cursor, s))
                menu.addAction(action)

            menu.addSeparator()

        # Add default options like copy/paste
        menu.addActions(self.createStandardContextMenu().actions())
        menu.exec(event.globalPos())

    def replaceWord(self, cursor, new_word):
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText(new_word)
        cursor.endEditBlock()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Create splash screen first
    splash = SplashScreen()
    splash.show()
    app.processEvents()
    
    # Create main window but don't show it yet
    window = LangoTangoWordProcessor()
    
    def init_window():
        splash.close()
        if window.initialize_project():
            window.show()
        else:
            # Clean up before quitting
            window.cleanup_threads()
            sys.exit(0)
            
    # Show splash for 2 seconds then initialize
    QTimer.singleShot(2000, init_window)
    
    result = app.exec()
    # Clean up before exit
    window.cleanup_threads()
    sys.exit(result)