# Iteration 22 - First-run correction feedback

1. [Function] Changing model provider left an obsolete validation error; provider changes now clear it.
2. [Function] Changing voice provider left an obsolete validation error; voice changes now clear it.
3. [Function] Correcting the model name left the old error visible; model edits now clear it.
4. [Function] The model key could trigger spellcheck handling; spellcheck is now disabled.
5. [Function] Correcting the model key left the old error visible; key edits now clear it.
6. [Function] Correcting a custom Base URL left the old error visible; URL edits now clear it.
7. [Design] The DashScope key lacked a stable form name; it now uses `aliyunApiKey`.
8. [Function] The DashScope key could trigger spellcheck handling; spellcheck is now disabled.
9. [Function] DashScope required state was only implicit; `aria-required=true` is now explicit.
10. [Function] Correcting the DashScope key left the old error visible; key edits now clear it.
