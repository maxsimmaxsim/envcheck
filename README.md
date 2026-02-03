# envcheck

**envcheck** is a single-run utility for checking whether a project or command can start in the current environment.

---

## What it does

- accepts a file, directory, or command as input  
- detects the runtime environment  
- collects basic environment facts  
- performs one attempt to start the target  
- returns a binary result

---

## Output

- **STDOUT:** `SUCCESS` or `FAIL` (single line)  
- **Exit code:** `0` or `1`  
- **Log file:** `./envcheck.log`  
  - up to 10 lines  
  - facts only  
  - no advice, no interpretation

---

## Result semantics

- `SUCCESS` means the target started successfully  
  or the run was not applicable (for example, library projects)
- `FAIL` means the target could not be started  
  in the current environment

envcheck does not explain causes and does not suggest fixes.

---

## Scope and limitations

- envcheck may execute the target code  
- envcheck does not modify the environment  
- envcheck does not validate business logic  
- envcheck does not guarantee correctness  

Use only on repositories or commands you trust,  
or inside an isolated environment.

---

## License and distribution

Commercial license and pre-built packages are available here:  
<link>

---

## Status

envcheck is a finished utility with fixed execution semantics.  
No roadmap. No required updates.