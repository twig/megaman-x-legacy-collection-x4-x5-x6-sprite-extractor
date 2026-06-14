@REM Rename all "*_level.png" to "*_level-baseline.png" for git diff comparison.
for %%f in (progress-baseline\*_level.png) do (
    del "%%~dpf%%~nf-baseline%%~xf" 2>nul
    ren "%%f" "%%~nf-baseline%%~xf"
)

for %%f in (progress-baseline\X4\*_level.png) do (
    del "%%~dpf%%~nf-baseline%%~xf" 2>nul
    ren "%%f" "%%~nf-baseline%%~xf"
)

for %%f in (progress-baseline\X6\*_level.png) do (
    del "%%~dpf%%~nf-baseline%%~xf" 2>nul
    ren "%%f" "%%~nf-baseline%%~xf"
)
