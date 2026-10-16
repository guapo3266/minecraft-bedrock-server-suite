// SOLO QA: simulador de consola. No contiene ni ejecuta Minecraft/BDS.
using System;
using System.IO;
using System.Threading;

class PortableStub {
    static void Main() {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        bool player = Environment.GetEnvironmentVariable("PORTABLE_QA_PLAYERS") == "1";
        Console.WriteLine("[INFO] Version: 1.21.0.3");
        Console.WriteLine("[INFO] Server started.");
        if (player) Console.WriteLine("[INFO] Player connected: JugadorQA, xuid: 123456789");
        string line;
        while ((line = Console.ReadLine()) != null) {
            if (line == "list") {
                Console.WriteLine("[INFO] There are " + (player ? "1" : "0") + "/10 players online:");
                if (player) Console.WriteLine("JugadorQA");
            } else if (line == "save query") {
                Console.WriteLine("[INFO] Data saved. Files are now ready to be copied.");
                Console.WriteLine("MundoPrueba/level.dat:" + new FileInfo("worlds/MundoPrueba/level.dat").Length);
            } else if (line == "stop") {
                Thread.Sleep(1500);
                Console.WriteLine("[INFO] Quit correctly");
                return;
            }
        }
    }
}
