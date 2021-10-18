import exoscale
import paramiko
import os
import time
#YOUR API KEY AND API SECRET HERE
API_KEY = "EXO9782e0d6742f33e3bcd5a757"
API_SECRET= "tUyML12tIzw3VQKqzQockuU71pbStx0Pv1W_IMrZCx0"
KEY_NAME = "exoscale_tp_key"
SSH_PRIVATE_KEY_FILE = "id_rsa_exoscale_tp"
#YOU NEED TO CHANGE THAT IN ORDER TO POINT TO YOUR OWN HOME DIR
HOME_DIR = "simoncorboz"
PRIVATE_NETWORK_NAME= "tp_private_network"
#enter following commands in your shell
#export EXOSCALE_API_KEY="EXO9782e0d6742f33e3bcd5a757"
#export EXOSCALE_API_SECRET="tUyML12tIzw3VQKqzQockuU71pbStx0Pv1W_IMrZCx0"
class Deployer():
    exo = None
    security_groups = None
    backend = None
    frontend= None
    database = None
    security_group_web = None
    security_group_database = None
    security_group_all = None
    zone_gva2= None
    key=None
    public_key=None
    private_key=None
    private_network= None
    private_key = None
    def init(self):
        self.exo = exoscale.Exoscale()
        #self.key = self.exo.compute.create_ssh_key(KEY_NAME)
        self.zone_gva2 = self.exo.compute.get_zone("ch-gva-2")
        #let us see if the private key already_exists
        #only works for unix and macos systems
        #first test if the key exist on the console
        try:
            self.key = self.exo.compute.get_ssh_key(KEY_NAME)
            if(os.path.exists("/Users/{}/.ssh/{}".format(HOME_DIR,SSH_PRIVATE_KEY_FILE))):
                self.private_key = open("/Users/{}/.ssh/{}".format(HOME_DIR,SSH_PRIVATE_KEY_FILE),'r').read()
            else:
                print("STOPPING DEPLOYMENT, OPEN YOUR EXOSCALE CONSOLE AND DELETE YOUR PUBLIC KEY NAMED exoscale_tp_key")
                print("THEN RESTART DEPLOYMENT")
                return
            self.key.private_key = self.private_key
            print(self.key.private_key)
        except exoscale.api.ResourceNotFoundError:
            self.key = self.exo.compute.create_ssh_key(KEY_NAME)
            self.private_key = self.key.private_key
            #save the private key
            text_file = None
            if(os.path.exists("/Users/{}/.ssh/{}".format(HOME_DIR,SSH_PRIVATE_KEY_FILE))):
                #clear the file
                open("/Users/{}/.ssh/{}".format(HOME_DIR,SSH_PRIVATE_KEY_FILE), "w").close()
                text_file = open("/Users/{}/.ssh/{}".format(HOME_DIR,SSH_PRIVATE_KEY_FILE), "wt")
            else:
                text_file = open("/Users/{}/.ssh/{}".format(HOME_DIR,SSH_PRIVATE_KEY_FILE),"w")
            text_file.write(self.key.private_key)
            text_file.close()
    def create_private_network(self):#this is like the vpc
        #create an unmanaged private network, we will have to manually address each instance
        try:
            self.private_network = self.exo.compute.get_private_network(self.zone_gva2,PRIVATE_NETWORK_NAME)
        except exoscale.api.ResourceNotFoundError:
            #create_private_network(zone, name, description='', start_ip=None, end_ip=None, netmask=None)
            print("Did not find the private network ->> creating it ")
            self.private_network = self.exo.compute.create_private_network(self.zone_gva2,PRIVATE_NETWORK_NAME,description="this is the private network for our tp")
    def create_security_group(self):

        self.security_group_web = self.exo.compute.create_security_group("web")
        for rule in [
            exoscale.api.compute.SecurityGroupRule.ingress(
                description="HTTP",
                network_cidr="0.0.0.0/0",
                port="80",
                protocol="tcp",
            ),
            exoscale.api.compute.SecurityGroupRule.ingress(
                description="HTTPS",
                network_cidr="0.0.0.0/0",
                port="443",
                protocol="tcp",
            ),
            exoscale.api.compute.SecurityGroupRule.ingress(
                description="HTTP",
                network_cidr="0.0.0.0/0",
                port="8080",
                protocol="tcp",
            ),
        ]:self.security_group_web.add_rule(rule)

        self.security_group_all = self.exo.compute.create_security_group("all")
        for rule in [
            exoscale.api.compute.SecurityGroupRule.ingress(
                description="SSH",
                network_cidr="0.0.0.0/0",
                port="22",
                protocol="tcp",
            ),
            exoscale.api.compute.SecurityGroupRule.ingress(
                description="PING",
                network_cidr="0.0.0.0/0",
                icmp_code="0",
                icmp_type="8",
                protocol="icmp",
            ),
        ]:self.security_group_all.add_rule(rule)

        self.security_group_database = self.exo.compute.create_security_group("database")
        for rule in [
            exoscale.api.compute.SecurityGroupRule.ingress(
                description="mysql",
                network_cidr="0.0.0.0/0",
                port="3306",
                protocol="tcp",
            ),
        ]:self.security_group_database.add_rule(rule)
    def create_database_instance(self):
        self.database = self.exo.compute.create_instance(
            name="tpdatabase",
            zone=self.zone_gva2,
            type=self.exo.compute.get_instance_type("medium"),#we do want a medium instance -> 4gig RAM and 2 processors
            template=list(
                self.exo.compute.list_instance_templates(
                    self.zone_gva2,
                    "Linux Ubuntu 20.04 LTS 64-bit"))[0],#
            volume_size=50,#50 gigs of storage is all we need
            security_groups=[self.security_group_all,self.security_group_database],
            private_networks=[self.private_network],
            ssh_key=self.key,
            user_data="""
            #cloud-config
            write_files:
            - path: /etc/netplan/eth1.yaml
              content: |
                network:
                  version: 2
                  ethernets:
                    eth1:
                      addresses:
                        - 10.0.0.1/24
            ssh_pwauth: False
            runcmd:
                - [ netplan, apply ]
                - sudo apt-get -y update
                - sudo apt-get -y install mysql-server
                - mkdir /home/ubuntu/workspace
                - sudo git clone https://github.com/simonmse/backend.git /home/ubuntu/workspace
                - chmod +x /home/ubuntu/workspace/db-init.sh
                - sudo /home/ubuntu/workspace/db-init.sh
                - cat /home/ubuntu/workspace/init.sql | sudo mysql -u root
                - sudo service mysql restart"""#we have to restart the mysql-server service in order to listen to incoming connections
        )
    def create_backend_instance(self):
        self.backend = self.exo.compute.create_instance(
            name="tpbackend",
            zone=self.zone_gva2,
            type=self.exo.compute.get_instance_type("medium"),#we do want a medium instance -> 4gig RAM and 2 processors
            template=list(
                self.exo.compute.list_instance_templates(
                    self.zone_gva2,
                    "Linux Ubuntu 20.04 LTS 64-bit"))[0],#
            volume_size=50,#50 gigs of storage is all we need
            security_groups=[self.security_group_all,self.security_group_web],#we do not need it to accept outside connection
            private_networks=[self.private_network],
            ssh_key=self.key,
            user_data="""
            #cloud-config
            write_files:
            - path: /etc/netplan/eth1.yaml
              content: |
                network:
                  version: 2
                  ethernets:
                    eth1:
                      addresses:
                        - 10.0.0.2/24
            ssh_pwauth: False
            runcmd:
                - [ netplan, apply ]
                - sudo apt-get -y update
                - sudo apt-get -y install default-jdk
                - sudo apt-get -y install maven
                - mkdir /home/ubuntu/workspace
                - sudo git clone https://github.com/CloudSys-GJ/backend.git /home/ubuntu/workspace
                - cd /home/ubuntu/workspace
                - sudo mvn spring-boot:run -Dspring-boot.run.arguments=--spring.datasource.url=jdbc:mysql://10.0.0.1:3306/db_counter
                """
        )
    def create_frontend_instance(self):
        self.frontend = self.exo.compute.create_instance(
            name="tpfrontend",
            zone=self.zone_gva2,
            type=self.exo.compute.get_instance_type("medium"),#we do want a medium instance -> 4gig RAM and 2 processors
            template=list(
                self.exo.compute.list_instance_templates(
                    self.zone_gva2,
                    "Linux Ubuntu 20.04 LTS 64-bit"))[0],#
            volume_size=50,#50 gigs of storage is all we need
            security_groups=[self.security_group_all,self.security_group_web],#make it reachable from the outside
            private_networks=[self.private_network],
            ssh_key=self.key,
            user_data="""
            #cloud-config
            write_files:
            - path: /etc/netplan/eth1.yaml
              content: |
                network:
                  version: 2
                  ethernets:
                    eth1:
                      addresses:
                        - 10.0.0.3/24
            ssh_pwauth: False
            runcmd:
                - [ netplan, apply ]
                - sudo apt-get -y update
                - sudo apt-get install -y npm
                - sudo apt-get install -y nodejs
                - mkdir /home/ubuntu/workspace
                - sudo git clone https://github.com/CloudSys-GJ/frontend.git /home/ubuntu/workspace
                - cd /home/ubuntu/workspace
                - npm install
                - node app.js {}""".format(self.backend.ipv4_address)
        )
def deploy():
    deployer = Deployer()
    deployer.init()
    deployer.create_security_group()
    deployer.create_private_network()
    deployer.create_database_instance()
    time.sleep(200)
    deployer.create_backend_instance()
    time.sleep(200)
    deployer.create_frontend_instance()
    time.sleep(100)
    print("DONE")
    print("THE WEBAPP IS AVAILABLE ON")
    print("http://{}:80".format(deployer.frontend.ipv4_address))
deploy()