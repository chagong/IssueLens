# Area Owners Template

This file defines technical areas and their owners for automatic issue assignment.

## Format

Each area section should contain:
- **Keywords**: Terms that indicate an issue belongs to this area
- **Paths**: File/folder paths associated with this area (optional)
- **Owners**: GitHub usernames or team handles to assign

---

## Debugging
- **Keywords**: debugger, breakpoint, launch.json, debug console, step through, debug adapter, DAP, attach, remote debug
- **Paths**: src/debugger/**, extension/debug/**, launch.json
- **Owners**: @debugger-owner

## Language Server / IntelliSense
- **Keywords**: IntelliSense, completion, hover, go to definition, LSP, language server, code actions, diagnostics, symbols
- **Paths**: src/languageserver/**, src/lsp/**
- **Owners**: @lsp-owner

## Build & Compile
- **Keywords**: build, compile, maven, gradle, ant, classpath, build path, compilation error, project import
- **Paths**: src/build/**, src/project/**
- **Owners**: @build-owner

## Testing
- **Keywords**: test, junit, testng, test runner, test explorer, test discovery, coverage
- **Paths**: src/test/**, src/testing/**
- **Owners**: @test-owner

## Refactoring
- **Keywords**: refactor, rename, extract method, move class, inline, code action
- **Paths**: src/refactoring/**
- **Owners**: @refactor-owner

## Formatting
- **Keywords**: format, formatter, indentation, code style, checkstyle, prettier
- **Paths**: src/formatter/**
- **Owners**: @format-owner

## Documentation
- **Keywords**: docs, documentation, readme, wiki, help, tutorial
- **Paths**: docs/**, *.md
- **Owners**: @docs-owner

---

## Notes

1. **Keywords** are matched case-insensitively against issue title, body, and labels
2. **Paths** use glob patterns and match mentioned file paths in issues
3. **Owners** can be individual users (@username) or teams (@org/team-name)
4. An issue can match multiple areas; the area with most keyword matches wins
5. If tied, the first matching area in file order is used
