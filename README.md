# LangoTango - A local language model powered language learning partner

[![temp-Image6-YUjt-Y.avif](https://i.postimg.cc/ncq5tdfd/temp-Image6-YUjt-Y.avif)](https://postimg.cc/MvKt7mTR)

## Feature Overview

LangoTango is a simple but powerful word processor designed for language learners seeking enhanced learning while being entertained. It offers comprehensive tools for efficient document creation and management and built in AI assistants who offer you feedback while you take lesson notes and do language tutorials

**Organised Workspace** - Intuitive management of folders, documents, and research materials for streamlined project organization

**Comprehensive tools and compatability** - Rich text formatting and minimal interface that helps you stay focused. Once you're done writing, ask a local language model for a review, or send your document to other writing apps for more formatting and delivery options

**AI Assistance** - Collaborate with AI assistants to improve your learning and language skills. They can spot regular spelling mistakes or tell you when you need improving. Add new languages with the Language Manager simply by naming the language and and giving the AI language teacher traits

[![temp-Imagea-YHW4l.avif](https://i.postimg.cc/tC1rXBQ0/temp-Imagea-YHW4l.avif)](https://postimg.cc/zVrw7SGp)

**Versatile Export Options** - Multiple export formats including Open Document, PDF, Plain Text, and Final Draft for screenwriters who need to write in different languages

**Automatic Backups** - Continuous auto-save functionality with timestamped backups stored in your home directory

**Built-in File Memory** - A file format that keeps track of history states. Even if you close the app, LangoTango documents can still undo changes you made before you last closed the document. Just click on the document name in the file manager and hit the undo keyboard shortcut to unlock the file's history

**Advanced Search and Replace** - Search tools to locate and modify content with quickly

## Keyboard Shortcuts

Increase your productivity with these essential shortcuts:

- Ctrl+O - Open Document
- Ctrl+S - Save Document
- Ctrl+M - Import Text
- Ctrl+E - Export Text
- Ctrl+N - New Folder
- Ctrl+D - New Document
- Ctrl+F - Find/Replace
- Ctrl+L - Highlight
- Ctrl+1 - Align Left
- Ctrl+2 - Align Center
- Ctrl+3 - Align Right
- Ctrl+4 - Justify
- Ctrl+Z - Undo
- Ctrl+Y - Redo
- Ctrl+W - Close Window

## Screenshots

AI assistance at your side all the time

[![temp-Image6ki-CCw.avif](https://i.postimg.cc/c1DxqLZ9/temp-Image6ki-CCw.avif)](https://postimg.cc/HjyDXHrX)

Query your documents to get a lesson review, ask for translations and more.

[![temp-Image-Nj-EB86.avif](https://i.postimg.cc/YqhptBCp/temp-Image-Nj-EB86.avif)](https://postimg.cc/N5vhxVXV)

## Installation

Download the builds for macOS and Windows or if you want to build your own for macOS, Windows or Linux you'll need:

1. PySide6

pip install PySide6

2. Spellchecker

pip install pyspellchecker

3. Ollama or LM Studio

[Ollama](https://ollama.com/)
[LM Studio](https://lmstudio.ai/)


Then git clone or download this repo:

```
git https://github.com/shokuninstudio/LangoTango.git
cd langotango
python langotango.py
```

If you are going to build it with Pyinstaller - langotango.ico, langotango_windows.py and langotango_windows.spec are for Windows (in the Windows folder).

## Hardware Requirements

The recommended language model is Gemma 3.

Fetch it from here:

12B version for GPUs with 16GB VRAM

ollama run gemma3:12b-it-qat

27B version for GPUs with more than 16GB VRAM

ollama run gemma3:27b-it-qat

## Important

LangoTango is hyper efficient and multi-threaded, but don't load multiple models at the same time unless you have a lot of VRAM!

Note, using language models to rewrite sections of text can cause loss of formatting because language models will generally only output left aligned plain text. 

## Issues

As LangoTango is a fork of Dillon, the word count tool won't work with writing systems such as Hanzi or Kanji which do not use spaces between words.

## Roadmap ahead

1. Notarisation / app signing.
2. Modular code. It's currently monolithic.
3. Manual.

---
*LangoTango by Shokunin Studio © 2025*

## License

This project is licensed under the GNU Lesser General Public License v3.0 (LGPL-3.0).

Since this project uses [PySide](https://doc.qt.io/qtforpython-6/licenses.html), it follows the LGPL requirements.
