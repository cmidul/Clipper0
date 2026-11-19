param([Parameter(Mandatory = $true)][string]$OutputPath)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $englishVoice = $synthesizer.GetInstalledVoices() |
        Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } |
        Select-Object -First 1
    if ($null -eq $englishVoice) {
        throw 'An installed English Windows speech voice is required for this test fixture.'
    }
    $synthesizer.SelectVoice($englishVoice.VoiceInfo.Name)
    $synthesizer.SetOutputToWaveFile($OutputPath)
    $synthesizer.Speak('Welcome to the video clipping test. We are checking automatic subtitles. This recording was generated locally. The final clip should have readable captions.')
}
finally {
    $synthesizer.Dispose()
}
