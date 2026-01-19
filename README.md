# Main Specialization project Fontys


This repository contains all the files and folders mentioned in the documentation for the Main project SAAS. 
The following list of folders and files are included in the project folder:

![folderStructure](/assets/project_folder_structure.png)

- The folder “auth_service” contains the authentication process and session control for the web site, written in python. Plus the requirements.txt which is a list for the required packages to run it

- The “config” folder contains the “users.json” file, which stores the users who can login to the website. Registration is not possible, the only way to get an account is by adding users to this JSON file.

- The “Dockerfile” is used for the building of the container.

- The “dosbox_conf” file is responsible for setting parameters for DOSBox like CPU or display settings and executing startup commands like mounting the Dos directory.

- The “dosDoom” folder is storing the game called “Doom”.

- The “keen” folder is storing the game called “Commander Keen”.

- The “nginx.conf” is the configuration file for nginx.

- The “start.sh” is a script which responsible for orchestrating the entire system startup, with some extra tasks, like setting environment variables for keyboard layout and display settings.

- The “warCraft” folder is storing the game called Warcraft.

- The “web” folder stores a html page with JS and CSS for the login landing page.