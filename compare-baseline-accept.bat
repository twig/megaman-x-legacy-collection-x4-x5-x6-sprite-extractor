@REM Rename all "*_level.png" to "*_level-baseline.png" for git diff comparison.
for %%f in (progress-baseline\*_level.png) do (
    del "%%~dpf%%~nf-baseline%%~xf" 2>nul
    ren "%%f" "%%~nf-baseline%%~xf"
)
