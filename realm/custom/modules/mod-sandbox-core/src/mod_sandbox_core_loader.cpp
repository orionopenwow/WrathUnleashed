/*
 * mod-sandbox-core loader. AzerothCore calls Add<module dir name, '-' as '_'>Scripts() for each module in
 * modules/ (the generated ModulesLoader.cpp).
 */

void AddSandboxCoreScripts();

void Addmod_sandbox_coreScripts()
{
    AddSandboxCoreScripts();
}
