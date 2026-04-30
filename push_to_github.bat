@echo off
echo ===================================
echo Pushing TON FlashBet to GitHub...
echo ===================================

E:
cd \SocialScanner\ton-flashbet

echo.
echo Checking git status...
git status

echo.
echo Pushing to GitHub...
git push -u origin master

if errorlevel 1 (
    echo.
    echo [ERROR] Push failed! Trying with force...
    git push -f origin master
)

echo.
echo Done! Check https://github.com/ignat-101/ton-flashbet
pause